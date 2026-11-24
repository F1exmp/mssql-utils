# mssql-utils

Утилиты для работы с MSSQL-проектом. Версия 0.2.0.

## Структура проекта

```text
mssql-utils/
├── src/
│   └── sql_description_checker.py      # проверка описаний таблицы и полей
├── tests/
│   ├── conftest.py
│   └── test_sql_description_checker.py # 23 теста
├── example/
│   └── table_example.sql               # пример CREATE TABLE с MS_Description
├── pyproject.toml
├── .gitignore
├── LICENSE
└── README.md
```

## Возможности

### Проверка описаний SQL-объектов

Консольная утилита `sql-description-checker` проверяет, что T-SQL скрипт
содержит описание таблицы и каждого её поля через расширенное свойство
`MS_Description` (`sp_addextendedproperty` / `sp_updateextendedproperty`).

Проверяются:

- наличие `CREATE TABLE` в скрипте;
- наличие описания у каждой таблицы;
- наличие описания у каждого поля таблицы;
- отсутствие описаний для несуществующих полей;
- непустота значения описания.

Парсер учитывает комментарии, строковые литералы, кавычки, квадратные
скобки, вложенные скобки и пакетные разделители `GO`. Поддерживаются несколько
таблиц в одном файле и разные схемы.

## Установка

Требуется Python 3.10+.

```bash
python -m venv .venv
# Windows PowerShell:
.venv\Scripts\Activate.ps1
# Linux/macOS:
# source .venv/bin/activate

pip install -e ".[dev]"
```

## Использование

Один или несколько файлов:

```bash
sql-description-checker example/table_example.sql
sql-description-checker example/table_example.sql other_script.sql
```

Запуск без установки:

```bash
python src/sql_description_checker.py example/table_example.sql
```

Дополнительные флаги:

- `-q`, `--quiet` — не выводить отчёт при успешной проверке;
- `--encoding NAME` — кодировка файлов (по умолчанию `utf-8-sig`);
- `--version` — показать версию утилиты.

Коды возврата:

- `0` — проблем нет;
- `1` — найдены проблемы в описаниях;
- `2` — ошибка запуска (файл не найден, ошибка кодировки, нет аргументов).

Пример вывода:

```text
Таблиц: 1, полей: 7
  dbo.CUSTOMER: 7 пол. (CUSTOMER_ID, CUSTOMER_FULL_NAME, CUSTOMER_EMAIL, CUSTOMER_PHONE, CUSTOMER_IS_ACTIVE, CUSTOMER_CREATED_AT, CUSTOMER_MODIFIED_AT)
OK: у таблицы и всех полей есть описание.
```

### Использование как библиотеки

```python
from pathlib import Path

import sql_description_checker as checker

result = checker.check_file(Path("example/table_example.sql"))
print(result.ok, result.tables, result.problems)

# Проверка текста без файла:
result = checker.check_sql("CREATE TABLE dbo.T (ID INT);")
```

Коды проблем доступны как константы: `CODE_NO_TABLES`,
`CODE_TABLE_DESCRIPTION_MISSING`, `CODE_COLUMN_DESCRIPTION_MISSING`,
`CODE_COLUMN_DESCRIPTION_UNKNOWN`, `CODE_DESCRIPTION_EMPTY`.

## Пример SQL

Файл [`example/table_example.sql`](example/table_example.sql) содержит пример
создания таблицы `dbo.CUSTOMER` на диалекте T-SQL. Таблица и каждое поле описаны
через `MS_Description`: описание таблицы размещено до `CREATE TABLE`, описания
полей — после.

## Разработка

- Исходный код: `src/`
- Тесты: `tests/`
- Докстринги: формат Google (`Args`, `Returns`, `Raises`, `Attributes`)

Запуск тестов:

```bash
pytest
```

## Лицензия

Проект распространяется на условиях лицензии, указанной в файле [LICENSE](LICENSE).
