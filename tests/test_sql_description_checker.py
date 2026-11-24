"""Тесты для модуля :mod:`sql_description_checker`."""

from __future__ import annotations

from pathlib import Path

import pytest

import sql_description_checker as checker


def table_sql(
    name: str = "CUSTOMER",
    columns: tuple[str, ...] = ("CUSTOMER_ID",),
    schema: str = "dbo",
) -> str:
    """Формирует простой SQL-файл с таблицей.

    Args:
        name: Имя таблицы.
        columns: Имена полей.
        schema: Имя схемы.

    Returns:
        Текст инструкции ``CREATE TABLE``.
    """
    definitions = ",\n".join(f"    {column} INT NULL" for column in columns)
    return f"CREATE TABLE {schema}.{name} (\n{definitions}\n);"


def property_sql(
    value: str = "Описание",
    table: str = "CUSTOMER",
    column: str | None = None,
    schema: str = "dbo",
    procedure: str = "sp_addextendedproperty",
    name: str = "MS_Description",
) -> str:
    """Формирует вызов расширенного свойства.

    Args:
        value: Значение описания.
        table: Имя таблицы.
        column: Имя поля или ``None`` для описания таблицы.
        schema: Имя схемы.
        procedure: Имя хранимой процедуры.
        name: Имя расширенного свойства.

    Returns:
        Текст инструкции ``EXEC``.
    """
    escaped_value = value.replace("'", "''")
    params = [
        f"@name = N'{name}'",
        f"@value = N'{escaped_value}'",
        "@level0type = N'SCHEMA'",
        f"@level0name = N'{schema}'",
        "@level1type = N'TABLE'",
        f"@level1name = N'{table}'",
    ]
    if column is not None:
        params.extend(["@level2type = N'COLUMN'", f"@level2name = N'{column}'"])
    return f"EXEC sys.{procedure}\n    " + ",\n    ".join(params) + ";"


def write_sql(tmp_path: Path, content: str, name: str = "script.sql") -> Path:
    """Создаёт временный SQL-файл для теста.

    Args:
        tmp_path: Временная директория pytest.
        content: Содержимое SQL-файла.
        name: Имя файла.

    Returns:
        Путь к созданному файлу.
    """
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return path


def test_strip_sql_comments_keeps_markers_inside_strings() -> None:
    """Удаляет комментарии, но сохраняет маркеры внутри строк."""
    sql = "SELECT N'-- not a comment /* also text */'; /* remove */ SELECT 2; -- tail\n"

    cleaned = checker.strip_sql_comments(sql)

    assert "N'-- not a comment /* also text */'" in cleaned
    assert "remove" not in cleaned
    assert "tail" not in cleaned
    assert "SELECT 2;" in cleaned


def test_iter_statements_ignores_semicolons_in_strings_and_parentheses() -> None:
    """Разбивает_sql на инструкции, игнорируя вложенные разделители."""
    sql = "SELECT N'a;b'; CREATE TABLE dbo.T (ID INT DEFAULT (1)); SELECT 2;"

    statements = list(checker.iter_statements(sql))

    assert len(statements) == 3
    assert "a;b" in statements[0]
    assert statements[1].startswith("CREATE TABLE")
    assert statements[2] == "SELECT 2"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("dbo.CUSTOMER", ("dbo", "CUSTOMER")),
        ("[dbo].[CUSTOMER]", ("dbo", "CUSTOMER")),
        ('"dbo"."CUSTOMER"', ("dbo", "CUSTOMER")),
        ("CUSTOMER", ("", "CUSTOMER")),
    ],
)
def test_split_qualified_name(raw: str, expected: tuple[str, str]) -> None:
    """Разделяет квалифицированное имя на схему и объект."""
    assert checker.split_qualified_name(raw) == expected


def test_parse_tables_supports_brackets_and_skips_constraints() -> None:
    """Извлекает поля таблицы и пропускает ограничения."""
    sql = """
    CREATE TABLE [dbo].[CUSTOMER] (
        [CUSTOMER_ID] INT NOT NULL,
        "CUSTOMER_NAME" VARCHAR(100) NOT NULL,
        CONSTRAINT PK_CUSTOMER PRIMARY KEY (CUSTOMER_ID),
        CONSTRAINT CK_NAME CHECK (LEN(CUSTOMER_NAME) > 0)
    );
    """

    tables = checker.parse_tables(sql)

    assert len(tables) == 1
    assert tables[0].qualified_name == "dbo.CUSTOMER"
    assert tables[0].columns == ["CUSTOMER_ID", "CUSTOMER_NAME"]


def test_parse_descriptions_handles_quotes_semicolon_and_update_procedure() -> None:
    """Разбирает значения с кавычками и точкой с запятой."""
    value = "Value; with 'quotes' and @name=N'inner'"
    sql = f"""
    EXECUTE sys.sp_updateextendedproperty
        @name = N'MS_Description',
        @value = N'{value.replace(chr(39), chr(39) * 2)}',
        @level0type = N'SCHEMA', @level0name = N'dbo',
        @level1type = N'TABLE', @level1name = N'[CUSTOMER]';
    """

    descriptions = checker.parse_descriptions(sql)

    assert len(descriptions) == 1
    assert descriptions[0].schema == "dbo"
    assert descriptions[0].table == "CUSTOMER"
    assert descriptions[0].column is None
    assert descriptions[0].value == value


def test_check_sql_reports_missing_table_description() -> None:
    """Сообщает об отсутствии описания таблицы."""
    sql = "\n".join(
        [table_sql(), property_sql(column="CUSTOMER_ID")]
    )

    result = checker.check_sql(sql)

    assert result.ok is False
    assert [problem.code for problem in result.problems] == [
        checker.CODE_TABLE_DESCRIPTION_MISSING
    ]


def test_check_sql_reports_missing_column_description() -> None:
    """Сообщает об отсутствии описания поля."""
    sql = "\n".join(
        [
            table_sql(columns=("CUSTOMER_ID", "CUSTOMER_NAME")),
            property_sql(),
            property_sql(column="CUSTOMER_ID"),
        ]
    )

    result = checker.check_sql(sql)

    assert [problem.code for problem in result.problems] == [
        checker.CODE_COLUMN_DESCRIPTION_MISSING
    ]
    assert "CUSTOMER_NAME" in result.problems[0].message


def test_check_sql_reports_unknown_column_description() -> None:
    """Сообщает об описании несуществующего поля."""
    sql = "\n".join(
        [
            table_sql(),
            property_sql(),
            property_sql(column="CUSTOMER_ID"),
            property_sql(column="UNKNOWN"),
        ]
    )

    result = checker.check_sql(sql)

    assert [problem.code for problem in result.problems] == [
        checker.CODE_COLUMN_DESCRIPTION_UNKNOWN
    ]


def test_check_sql_reports_empty_description() -> None:
    """Сообщает о пустом значении описания."""
    sql = "\n".join(
        [
            table_sql(columns=("CUSTOMER_ID", "CUSTOMER_NAME")),
            property_sql(value=""),
            property_sql(column="CUSTOMER_ID"),
            property_sql(column="CUSTOMER_NAME"),
        ]
    )

    result = checker.check_sql(sql)

    assert [problem.code for problem in result.problems] == [
        checker.CODE_DESCRIPTION_EMPTY
    ]


def test_check_sql_reports_no_tables() -> None:
    """Сообщает, если CREATE TABLE не найден."""
    result = checker.check_sql("SELECT 1;")

    assert [problem.code for problem in result.problems] == [checker.CODE_NO_TABLES]


def test_check_sql_accepts_descriptions_before_table() -> None:
    """Принимает описание таблицы до CREATE TABLE."""
    sql = "\n".join(
        [
            property_sql(),
            table_sql(),
            property_sql(column="CUSTOMER_ID"),
        ]
    )

    result = checker.check_sql(sql)

    assert result.ok
    assert result.column_count == 1
    assert len(result.descriptions) == 2


def test_check_sql_ignores_other_extended_properties() -> None:
    """Игнорирует расширенные свойства с другим именем."""
    sql = "\n".join(
        [
            property_sql(name="MS_Format"),
            table_sql(),
            property_sql(column="CUSTOMER_ID"),
        ]
    )

    result = checker.check_sql(sql)

    assert [problem.code for problem in result.problems] == [
        checker.CODE_TABLE_DESCRIPTION_MISSING
    ]


def test_check_sql_respects_schema() -> None:
    """Не переносит описания одной схемы на таблицу другой схемы."""
    sql = "\n".join(
        [
            table_sql(name="T", schema="dbo"),
            table_sql(name="T", schema="archive"),
            property_sql(table="T", schema="dbo"),
            property_sql(table="T", column="ID", schema="dbo"),
        ]
    )

    result = checker.check_sql(sql)

    assert [problem.code for problem in result.problems] == [
        checker.CODE_TABLE_DESCRIPTION_MISSING,
        checker.CODE_COLUMN_DESCRIPTION_MISSING,
    ]
    assert "archive.T" in result.problems[0].target


def test_check_file_handles_bom_and_crlf(tmp_path: Path) -> None:
    """Корректно читает файл с BOM и переводами строк CRLF."""
    sql = "\r\n".join(
        [
            property_sql(),
            table_sql(),
            property_sql(column="CUSTOMER_ID"),
        ]
    )
    path = tmp_path / "bom.sql"
    path.write_bytes(b"\xef\xbb\xbf" + sql.encode("utf-8"))

    result = checker.check_file(path)

    assert result.ok


def test_check_file_raises_error_for_missing_file(tmp_path: Path) -> None:
    """Сообщает об ошибке чтения несуществующего файла."""
    with pytest.raises(checker.SqlCheckError):
        checker.check_file(tmp_path / "missing.sql")


def test_print_report_quiet_suppresses_success(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """В тихом режиме не печатает отчёт при успехе."""
    result = checker.check_sql(
        "\n".join([property_sql(), table_sql(), property_sql(column="CUSTOMER_ID")])
    )

    checker.print_report(result, quiet=True)

    assert capsys.readouterr().out == ""


def test_main_returns_codes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Возвращает корректные коды завершения."""
    ok_path = write_sql(
        tmp_path,
        "\n".join([property_sql(), table_sql(), property_sql(column="CUSTOMER_ID")]),
        "ok.sql",
    )
    bad_path = write_sql(tmp_path, table_sql(), "bad.sql")

    assert checker.main([str(ok_path), "-q"]) == 0
    assert capsys.readouterr().out == ""
    assert checker.main([str(bad_path)]) == 1
    assert "Найдено проблем" in capsys.readouterr().out
    assert checker.main([str(tmp_path / "missing.sql")]) == 2
    assert "Ошибка" in capsys.readouterr().err


def test_main_version(capsys: pytest.CaptureFixture[str]) -> None:
    """Выводит версию утилиты."""
    assert checker.main(["--version"]) == 0
    assert checker.__version__ in capsys.readouterr().out


def test_main_requires_sql_file() -> None:
    """Требует указать хотя бы один SQL-файл."""
    with pytest.raises(SystemExit) as exc_info:
        checker.main([])
    assert exc_info.value.code == 2


def test_example_file_is_valid() -> None:
    """Проверяет штатный пример из репозитория."""
    repo_root = Path(__file__).resolve().parents[1]
    example = repo_root / "example" / "table_example.sql"

    result = checker.check_file(example)

    assert result.ok
    assert len(result.tables) == 1
    assert result.tables[0].name == "CUSTOMER"
    assert result.column_count == 7
