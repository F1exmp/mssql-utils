#!/usr/bin/env python3
"""Проверка SQL-скрипта на наличие описаний таблицы и всех её полей.

Модуль разбирает T-SQL скрипт, находит выражения ``CREATE TABLE`` и вызовы
``sp_addextendedproperty`` / ``sp_updateextendedproperty`` со свойством
``MS_Description``, после чего проверяет:

* наличие описания у каждой таблицы;
* наличие описания у каждого поля каждой таблицы;
* отсутствие описаний для несуществующих полей;
* непустоту значения описания.

Пример использования как библиотеки:

    >>> result = check_sql("CREATE TABLE dbo.T (ID INT);")
    >>> result.ok
    False

Пример запуска как консольного приложения::

    python src/sql_description_checker.py example/table_example.sql

Коды возврата: ``0`` — проблем нет, ``1`` — найдены проблемы,
``2`` — ошибка запуска.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

__all__ = [
    "CheckResult",
    "Description",
    "Problem",
    "SqlCheckError",
    "Table",
    "build_parser",
    "check_file",
    "check_sql",
    "main",
    "parse_descriptions",
    "parse_tables",
    "print_report",
    "strip_sql_comments",
]

__version__ = "0.2.0"

DESCRIPTION_PROPERTY = "MS_DESCRIPTION"

CODE_NO_TABLES = "NO_TABLES"
CODE_TABLE_DESCRIPTION_MISSING = "TABLE_DESCRIPTION_MISSING"
CODE_COLUMN_DESCRIPTION_MISSING = "COLUMN_DESCRIPTION_MISSING"
CODE_COLUMN_DESCRIPTION_UNKNOWN = "COLUMN_DESCRIPTION_UNKNOWN"
CODE_DESCRIPTION_EMPTY = "DESCRIPTION_EMPTY"

_IDENTIFIER = r"(?:\[[^\]]+\]|\"[^\"]+\"|`[^`]+`|\w+)"
_CREATE_TABLE_RE = re.compile(
    rf"CREATE\s+TABLE\s+(?P<name>{_IDENTIFIER}(?:\s*\.\s*{_IDENTIFIER})?)",
    re.IGNORECASE,
)
_EXTENDED_PROPERTY_RE = re.compile(
    r"(?:EXEC(?:UTE)?\s+)?(?:sys\s*\.\s*)?"
    r"sp_(?:add|update)extendedproperty\b",
    re.IGNORECASE,
)
_COLUMN_TOKEN_RE = re.compile(
    r"^\s*(\[[^\]]+\]|\"[^\"]+\"|`[^`]+`|[A-Za-z_][\w$#@]*)"
)
_PARAMETER_RE = re.compile(r"@(\w+)\s*=\s*", re.IGNORECASE)

_NON_COLUMN_KEYWORDS = {
    "CONSTRAINT",
    "PRIMARY",
    "UNIQUE",
    "CHECK",
    "FOREIGN",
    "INDEX",
    "KEY",
    "PERIOD",
}


class SqlCheckError(Exception):
    """Ошибка чтения или обработки SQL-файла."""


@dataclass(frozen=True)
class Description:
    """Расширенное свойство ``MS_Description`` из SQL-скрипта.

    Attributes:
        schema: Схема объекта. ``None`` означает, что схема не указана.
        table: Имя таблицы.
        column: Имя поля или ``None``, если описан сам объект.
        value: Значение описания.
    """

    schema: Optional[str]
    table: str
    column: Optional[str]
    value: str

    @property
    def target(self) -> str:
        """Возвращает читаемое имя описанного объекта.

        Returns:
            Имя в формате ``schema.table.column`` или его часть.
        """
        parts = [part for part in (self.schema, self.table, self.column) if part]
        return ".".join(parts)


@dataclass
class Table:
    """Таблица, найденная в SQL-скрипте.

    Attributes:
        schema: Имя схемы. Пустая строка, если схема не указана.
        name: Имя таблицы.
        columns: Имена полей в порядке объявления.
    """

    schema: str
    name: str
    columns: List[str] = field(default_factory=list)

    @property
    def key(self) -> Tuple[str, str]:
        """Возвращает нормализованный ключ таблицы.

        Returns:
            Кортеж ``(schema, name)`` в верхнем регистре.
        """
        return self.schema.upper(), self.name.upper()

    @property
    def qualified_name(self) -> str:
        """Возвращает полное имя таблицы.

        Returns:
            Имя в формате ``schema.name`` или ``name``.
        """
        return f"{self.schema}.{self.name}" if self.schema else self.name


@dataclass(frozen=True)
class Problem:
    """Проблема, обнаруженная при проверке скрипта.

    Attributes:
        code: Машинночитаемый код проблемы.
        target: Объект, к которому относится проблема.
        message: Человекочитаемое описание проблемы.
    """

    code: str
    target: str
    message: str

    def __str__(self) -> str:
        """Возвращает строковое представление проблемы.

        Returns:
            Строка вида ``[target] message``.
        """
        return f"[{self.target}] {self.message}"


@dataclass
class CheckResult:
    """Результат проверки SQL-скрипта.

    Attributes:
        tables: Найденные таблицы.
        descriptions: Найденные описания ``MS_Description``.
        problems: Обнаруженные проблемы.
    """

    tables: List[Table] = field(default_factory=list)
    descriptions: List[Description] = field(default_factory=list)
    problems: List[Problem] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """Возвращает TRUE, если проблем не найдено.

        Returns:
            ``True`` при отсутствии проблем.
        """
        return not self.problems

    @property
    def column_count(self) -> int:
        """Возвращает общее количество полей во всех таблицах.

        Returns:
            Суммарное число полей.
        """
        return sum(len(table.columns) for table in self.tables)


def unquote_identifier(identifier: str) -> str:
    """Убирает обрамление SQL-идентификатора.

    Поддерживаются квадратные скобки, двойные кавычки и обратные кавычки.

    Args:
        identifier: Идентификатор в исходном виде.

    Returns:
        Идентификатор без внешнего обрамления.
    """
    identifier = identifier.strip()
    pairs = (("[", "]"), ('"', '"'), ("`", "`"))
    for opening, closing in pairs:
        if len(identifier) >= 2 and identifier.startswith(opening) and identifier.endswith(closing):
            return identifier[len(opening) : -len(closing)].replace(closing * 2, closing)
    return identifier


def split_qualified_name(raw: str) -> Tuple[str, str]:
    """Разделяет квалифицированное имя на схему и имя объекта.

    Args:
        raw: Имя вида ``dbo.CUSTOMER``, ``[dbo].[CUSTOMER]`` или ``CUSTOMER``.

    Returns:
        Кортеж ``(schema, name)``. Если схема не указана, первым элементом
        будет пустая строка.
    """
    parts = [unquote_identifier(part) for part in re.findall(_IDENTIFIER, raw)]
    if not parts:
        return "", ""
    if len(parts) == 1:
        return "", parts[0]
    return parts[-2], parts[-1]


def strip_sql_comments(sql: str) -> str:
    """Удаляет блочные и строчные комментарии из SQL-текста.

    Маркеры комментариев внутри строковых литералов и идентификаторов
    не трогаются. Переводы строк сохраняются.

    Args:
        sql: Исходный SQL-текст.

    Returns:
        SQL-текст без комментариев.
    """
    output: List[str] = []
    index = 0
    length = len(sql)

    while index < length:
        char = sql[index]

        if char == "'":
            end = _skip_quoted(sql, index)
            output.append(sql[index:end])
            index = end
            continue

        if char == "[":
            end = _skip_bracketed(sql, index)
            output.append(sql[index:end])
            index = end
            continue

        if sql.startswith("--", index):
            end = sql.find("\n", index)
            if end == -1:
                break
            output.append("\n")
            index = end + 1
            continue

        if sql.startswith("/*", index):
            end = sql.find("*/", index + 2)
            if end == -1:
                break
            output.extend(["\n"] * sql.count("\n", index, end))
            index = end + 2
            continue

        output.append(char)
        index += 1

    return "".join(output)


def _skip_quoted(text: str, start: int) -> int:
    """Возвращает индекс после закрывающей одиночной кавычки.

    Args:
        text: Исходный текст.
        start: Индекс открывающей кавычки.

    Returns:
        Индекс символа сразу после закрывающей кавычки или длина текста,
        если кавычка не закрыта.
    """
    index = start + 1
    while index < len(text):
        if text[index] == "'":
            if index + 1 < len(text) and text[index + 1] == "'":
                index += 2
                continue
            return index + 1
        index += 1
    return len(text)


def _skip_bracketed(text: str, start: int) -> int:
    """Возвращает индекс после закрывающей квадратной скобки.

    Args:
        text: Исходный текст.
        start: Индекс открывающей скобки.

    Returns:
        Индекс символа сразу после закрывающей скобки или длина текста,
        если скобка не закрыта.
    """
    index = start + 1
    while index < len(text):
        if text[index] == "]":
            if index + 1 < len(text) and text[index + 1] == "]":
                index += 2
                continue
            return index + 1
        index += 1
    return len(text)


def iter_statements(sql: str) -> Iterable[str]:
    """Разбивает SQL-текст на инструкции по символу ``;``.

    Разделители внутри строковых литералов, идентификаторов и скобок
    игнорируются.

    Args:
        sql: SQL-текст без комментариев.

    Yields:
        Очередная инструкция без завершающей точки с запятой.
    """
    buffer: List[str] = []
    depth = 0
    index = 0
    length = len(sql)

    while index < length:
        char = sql[index]

        if char == "'":
            end = _skip_quoted(sql, index)
            buffer.append(sql[index:end])
            index = end
            continue

        if char == "[":
            end = _skip_bracketed(sql, index)
            buffer.append(sql[index:end])
            index = end
            continue

        if char == '"' or char == "`":
            closing = char * 2
            end = index + 1
            while end < length:
                if sql[end] == char:
                    if sql.startswith(closing, end):
                        end += 2
                        continue
                    end += 1
                    break
                end += 1
            buffer.append(sql[index:end])
            index = end
            continue

        if char == "(":
            depth += 1
        elif char == ")":
            depth = max(0, depth - 1)

        if char == ";" and depth == 0:
            statement = "".join(buffer).strip()
            if statement:
                yield statement
            buffer = []
        else:
            buffer.append(char)

        index += 1

    statement = "".join(buffer).strip()
    if statement:
        yield statement


def _matching_paren(text: str, open_index: int) -> Optional[int]:
    """Находит закрывающую скобку для заданной открывающей.

    Args:
        text: Текст, в котором выполняется поиск.
        open_index: Индекс открывающей скобки.

    Returns:
        Индекс соответствующей закрывающей скобки или ``None``.
    """
    depth = 0
    index = open_index
    while index < len(text):
        char = text[index]

        if char == "'":
            index = _skip_quoted(text, index)
            continue
        if char == "[":
            index = _skip_bracketed(text, index)
            continue

        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return index

        index += 1

    return None


def split_top_level(body: str) -> List[str]:
    """Делит тело ``CREATE TABLE`` по запятым верхнего уровня.

    Запятые внутри скобок, строковых литералов и identifiers не считаются
    разделителями.

    Args:
        body: Текст между открывающей и закрывающей скобками ``CREATE TABLE``.

    Returns:
        Список определений столбцов и ограничений.
    """
    parts: List[str] = []
    buffer: List[str] = []
    depth = 0
    index = 0

    while index < len(body):
        char = body[index]

        if char == "'":
            end = _skip_quoted(body, index)
            buffer.append(body[index:end])
            index = end
            continue

        if char == "[":
            end = _skip_bracketed(body, index)
            buffer.append(body[index:end])
            index = end
            continue

        if char == "(":
            depth += 1
        elif char == ")":
            depth = max(0, depth - 1)

        if char == "," and depth == 0:
            part = "".join(buffer).strip()
            if part:
                parts.append(part)
            buffer = []
        else:
            buffer.append(char)

        index += 1

    part = "".join(buffer).strip()
    if part:
        parts.append(part)

    return parts


def parse_columns(body: str) -> List[str]:
    """Извлекает имена полей из тела ``CREATE TABLE``.

    Определения ограничений (``CONSTRAINT``, ``PRIMARY KEY`` и т. п.)
    пропускаются.

    Args:
        body: Текст внутри скобок ``CREATE TABLE``.

    Returns:
        Список уникальных имён полей в порядке объявления.
    """
    columns: List[str] = []
    seen: Set[str] = set()

    for definition in split_top_level(body):
        match = _COLUMN_TOKEN_RE.match(definition)
        if not match:
            continue

        name = unquote_identifier(match.group(1))
        key = name.upper()
        if key in _NON_COLUMN_KEYWORDS or key in seen:
            continue

        seen.add(key)
        columns.append(name)

    return columns


def parse_tables(sql: str) -> List[Table]:
    """Находит все таблицы и их поля в SQL-скрипте.

    Args:
        sql: SQL-текст без комментариев.

    Returns:
        Список найденных таблиц. Повторные объявления одной таблицы
        объединяются.
    """
    tables: Dict[Tuple[str, str], Table] = {}

    for statement in iter_statements(sql):
        for match in _CREATE_TABLE_RE.finditer(statement):
            schema, name = split_qualified_name(match.group("name"))
            if not name:
                continue

            open_index = statement.find("(", match.end())
            if open_index == -1:
                continue

            close_index = _matching_paren(statement, open_index)
            if close_index is None:
                continue

            table = tables.setdefault(
                (schema.upper(), name.upper()), Table(schema=schema, name=name)
            )
            for column in parse_columns(statement[open_index + 1 : close_index]):
                if column.upper() not in {existing.upper() for existing in table.columns}:
                    table.columns.append(column)

    return list(tables.values())


def parse_parameters(text: str) -> Dict[str, str]:
    """Извлекает именованные параметры вызова расширенного свойства.

    Args:
        text: Текст инструкции ``EXEC sp_*extendedproperty``.

    Returns:
        Словарь ``{имя_параметра_в_нижнем_регистре: значение}``.
    """
    params: Dict[str, str] = {}
    index = 0

    while index < len(text):
        char = text[index]
        if char == "'":
            index = _skip_quoted(text, index)
            continue
        if char == "[":
            index = _skip_bracketed(text, index)
            continue

        match = _PARAMETER_RE.match(text, index)
        if not match:
            index += 1
            continue

        name = match.group(1).lower()
        value_index = match.end()
        if (
            value_index + 1 < len(text)
            and text[value_index] in "Nn"
            and text[value_index + 1] == "'"
        ):
            value_index += 1

        if value_index < len(text) and text[value_index] == "'":
            end = _skip_quoted(text, value_index)
            raw_value = text[value_index + 1 : end - 1] if end > value_index + 1 else ""
            params[name] = raw_value.replace("''", "'")
            index = end
            continue

        end = text.find(",", value_index)
        if end == -1:
            end = len(text)
        params[name] = text[value_index:end].strip().strip("\"'")
        index = end + 1

    return params


def parse_descriptions(sql: str) -> List[Description]:
    """Собирает описания ``MS_Description`` из SQL-скрипта.

    Учитываются вызовы ``sp_addextendedproperty`` и
    ``sp_updateextendedproperty``.

    Args:
        sql: SQL-текст без комментариев.

    Returns:
        Список найденных описаний.
    """
    descriptions: List[Description] = []

    for statement in iter_statements(sql):
        if not _EXTENDED_PROPERTY_RE.search(statement):
            continue

        params = parse_parameters(statement)
        if params.get("name", "").upper() != DESCRIPTION_PROPERTY:
            continue

        schema, table = split_qualified_name(params.get("level1name", ""))
        if not schema:
            schema = params.get("level0name", "").strip().strip("\"'[]")
        if not table:
            continue

        raw_column = params.get("level2name", "").strip()
        column = split_qualified_name(raw_column)[1] if raw_column else None
        descriptions.append(
            Description(
                schema=unquote_identifier(schema) or None,
                table=unquote_identifier(table),
                column=unquote_identifier(column) if column else None,
                value=params.get("value", ""),
            )
        )

    return descriptions


def _schema_matches(description_schema: Optional[str], table_schema: str) -> bool:
    """Проверяет соответствие схемы описания и схемы таблицы.

    Отсутствие схемы с любой стороны считается совпадением.

    Args:
        description_schema: Схема из описания или ``None``.
        table_schema: Схема таблицы.

    Returns:
        ``True``, если схемы совместимы.
    """
    if not description_schema or not table_schema:
        return True
    return description_schema.upper() == table_schema.upper()


def check_sql(sql: str) -> CheckResult:
    """Проверяет SQL-текст на наличие описаний таблиц и полей.

    Args:
        sql: Содержимое T-SQL скрипта.

    Returns:
        Результат проверки со списком найденных таблиц, описаний и проблем.
    """
    cleaned = strip_sql_comments(sql)
    tables = parse_tables(cleaned)
    descriptions = parse_descriptions(cleaned)
    result = CheckResult(tables=tables, descriptions=descriptions)

    if not tables:
        result.problems.append(
            Problem(CODE_NO_TABLES, "-", "в скрипте не найдено ни одного CREATE TABLE")
        )
        return result

    for table in tables:
        table_name = table.qualified_name

        table_descriptions = [
            description
            for description in descriptions
            if description.column is None
            and description.table.upper() == table.name.upper()
            and _schema_matches(description.schema, table.schema)
        ]
        if not table_descriptions:
            result.problems.append(
                Problem(
                    CODE_TABLE_DESCRIPTION_MISSING,
                    table_name,
                    "отсутствует описание таблицы",
                )
            )
        elif any(not description.value.strip() for description in table_descriptions):
            result.problems.append(
                Problem(
                    CODE_DESCRIPTION_EMPTY,
                    table_name,
                    "описание присутствует, но пустое",
                )
            )

        described_columns: Dict[str, Description] = {}
        for description in descriptions:
            if (
                description.column
                and description.table.upper() == table.name.upper()
                and _schema_matches(description.schema, table.schema)
            ):
                described_columns.setdefault(description.column.upper(), description)

        known_columns = {column.upper(): column for column in table.columns}

        for column in table.columns:
            description = described_columns.get(column.upper())
            if description is None:
                result.problems.append(
                    Problem(
                        CODE_COLUMN_DESCRIPTION_MISSING,
                        f"{table_name}.{column}",
                        f"отсутствует описание поля {column}",
                    )
                )
            elif not description.value.strip():
                result.problems.append(
                    Problem(
                        CODE_DESCRIPTION_EMPTY,
                        f"{table_name}.{column}",
                        "описание присутствует, но пустое",
                    )
                )

        for column_key in sorted(described_columns.keys() - known_columns.keys()):
            result.problems.append(
                Problem(
                    CODE_COLUMN_DESCRIPTION_UNKNOWN,
                    f"{table_name}.{described_columns[column_key].column}",
                    f"описание задано для несуществующего поля "
                    f"{described_columns[column_key].column}",
                )
            )

    return result


def check_file(path: Path, encoding: str = "utf-8-sig") -> CheckResult:
    """Проверяет SQL-файл на наличие описаний таблиц и полей.

    Args:
        path: Путь к проверяемому SQL-файлу.
        encoding: Кодировка файла.

    Returns:
        Результат проверки.

    Raises:
        SqlCheckError: Если файл не удаётся прочитать.
    """
    try:
        raw = path.read_text(encoding=encoding)
    except (OSError, UnicodeError) as error:
        raise SqlCheckError(f"не удалось прочитать файл {path}: {error}") from error

    return check_sql(raw)


def print_report(
    result: CheckResult,
    path: Optional[Path] = None,
    quiet: bool = False,
) -> None:
    """Печатает отчёт о проверке в стандартный вывод.

    Args:
        result: Результат проверки.
        path: Путь к файлу, если нужно вывести заголовок.
        quiet: Если ``True``, при отсутствии проблем вывод подавляется.
    """
    if quiet and result.ok:
        return

    if path is not None:
        print(f"=== {path} ===")

    print(f"Таблиц: {len(result.tables)}, полей: {result.column_count}")

    for table in result.tables:
        columns = f" ({', '.join(table.columns)})" if table.columns else ""
        print(f"  {table.qualified_name}: {len(table.columns)} пол.{columns}")

    if result.ok:
        print("OK: у таблицы и всех полей есть описание.")
        return

    print(f"Найдено проблем: {len(result.problems)}")
    for problem in result.problems:
        print(f"  {problem}")


def build_parser() -> argparse.ArgumentParser:
    """Создаёт парсер аргументов командной строки.

    Returns:
        Настроенный ``argparse.ArgumentParser``.
    """
    parser = argparse.ArgumentParser(
        prog="sql-description-checker",
        description=(
            "Проверяет, что SQL-скрипт содержит описание таблицы и всех её "
            "полей через расширенное свойство MS_Description."
        ),
    )
    parser.add_argument(
        "sql_files",
        nargs="*",
        type=Path,
        metavar="SQL_FILE",
        help="один или несколько проверяемых SQL-файлов",
    )
    parser.add_argument(
        "-q", "--quiet", action="store_true", help="не выводить отчёт при успешной проверке"
    )
    parser.add_argument(
        "--encoding", default="utf-8-sig", help="кодировка SQL-файлов (по умолчанию utf-8-sig)"
    )
    parser.add_argument(
        "--version",
        action="store_true",
        help="показать версию утилиты и выйти",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Точка входа консольного приложения.

    Args:
        argv: Аргументы командной строки. Если ``None``, используются
            ``sys.argv[1:]``.

    Returns:
        Код возврата процесса: ``0`` — проблем нет, ``1`` — найдены
        проблемы, ``2`` — ошибка запуска.
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.version:
        print(f"sql-description-checker {__version__}")
        return 0

    if not args.sql_files:
        parser.error("указайте хотя бы один SQL-файл")

    exit_code = 0
    for path in args.sql_files:
        try:
            result = check_file(path, encoding=args.encoding)
        except SqlCheckError as error:
            print(f"Ошибка: {error}", file=sys.stderr)
            exit_code = 2
            continue

        print_report(
            result,
            path=path if len(args.sql_files) > 1 else None,
            quiet=args.quiet,
        )
        if not result.ok and exit_code == 0:
            exit_code = 1

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
