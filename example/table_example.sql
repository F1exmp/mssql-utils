/*
    Пример создания таблицы в диалекте T-SQL.

    Каждое поле и сама таблица описаны расширенными свойствами (Extended Properties)
    в схеме MS_Description, что позволяет хранить бизнес-описание прямо в базе данных.

    Файл можно выполнить целиком в SSMS, Azure Data Studio или sqlcmd.
*/

/* Описание таблицы */
EXEC sys.sp_addextendedproperty
     @name = N'MS_Description',
     @value = N'Клиенты компании: контактные данные и статус учётной записи.',
     @level0type = N'SCHEMA', @level0name = N'dbo',
     @level1type = N'TABLE', @level1name = N'CUSTOMER';
GO

/* Создание таблицы */
CREATE TABLE dbo.CUSTOMER
(
    CUSTOMER_ID INT IDENTITY (1, 1) NOT NULL,
    CUSTOMER_FULL_NAME VARCHAR(200) NOT NULL,
    CUSTOMER_EMAIL VARCHAR(320) NULL,
    CUSTOMER_PHONE VARCHAR(32) NULL,
    CUSTOMER_IS_ACTIVE BIT NOT NULL CONSTRAINT DF_CUSTOMER_IS_ACTIVE DEFAULT (1),
    CUSTOMER_CREATED_AT DATETIME2(0) NOT NULL CONSTRAINT DF_CUSTOMER_CREATED_AT DEFAULT (SYSUTCDATETIME()),
    CUSTOMER_MODIFIED_AT DATETIME2(0) NULL,

    CONSTRAINT PK_CUSTOMER PRIMARY KEY CLUSTERED (CUSTOMER_ID)
);

GO

/* Описание полей */

/* CUSTOMER_ID */
EXEC sys.sp_addextendedproperty
     @name = N'MS_Description',
     @value = N'Уникальный идентификатор клиента (суррогатный первичный ключ).',
     @level0type = N'SCHEMA', @level0name = N'dbo',
     @level1type = N'TABLE', @level1name = N'CUSTOMER',
     @level2type = N'COLUMN', @level2name = N'CUSTOMER_ID';
GO

/* CUSTOMER_FULL_NAME */
EXEC sys.sp_addextendedproperty
     @name = N'MS_Description',
     @value = N'Полное наименование клиента (для физлица — ФИО, для юрлица — название организации).',
     @level0type = N'SCHEMA', @level0name = N'dbo',
     @level1type = N'TABLE', @level1name = N'CUSTOMER',
     @level2type = N'COLUMN', @level2name = N'CUSTOMER_FULL_NAME';
GO

/* CUSTOMER_EMAIL */
EXEC sys.sp_addextendedproperty
     @name = N'MS_Description',
     @value = N'Адрес электронной почты. Уникален в пределах таблицы, может быть не указан.',
     @level0type = N'SCHEMA', @level0name = N'dbo',
     @level1type = N'TABLE', @level1name = N'CUSTOMER',
     @level2type = N'COLUMN', @level2name = N'CUSTOMER_EMAIL';
GO

/* CUSTOMER_PHONE */
EXEC sys.sp_addextendedproperty
     @name = N'MS_Description',
     @value = N'Контактный телефон в свободном формате, включая код страны.',
     @level0type = N'SCHEMA', @level0name = N'dbo',
     @level1type = N'TABLE', @level1name = N'CUSTOMER',
     @level2type = N'COLUMN', @level2name = N'CUSTOMER_PHONE';
GO

/* CUSTOMER_IS_ACTIVE */
EXEC sys.sp_addextendedproperty
     @name = N'MS_Description',
     @value = N'Признак активности учётной записи: 1 — активна, 0 — заблокирована.',
     @level0type = N'SCHEMA', @level0name = N'dbo',
     @level1type = N'TABLE', @level1name = N'CUSTOMER',
     @level2type = N'COLUMN', @level2name = N'CUSTOMER_IS_ACTIVE';
GO

/* CUSTOMER_CREATED_AT */
EXEC sys.sp_addextendedproperty
     @name = N'MS_Description',
     @value = N'Дата и время создания записи в UTC. Заполняется автоматически.',
     @level0type = N'SCHEMA', @level0name = N'dbo',
     @level1type = N'TABLE', @level1name = N'CUSTOMER',
     @level2type = N'COLUMN', @level2name = N'CUSTOMER_CREATED_AT';
GO

/* CUSTOMER_MODIFIED_AT */
EXEC sys.sp_addextendedproperty
     @name = N'MS_Description',
     @value = N'Дата и время последнего изменения записи в UTC.',
     @level0type = N'SCHEMA', @level0name = N'dbo',
     @level1type = N'TABLE', @level1name = N'CUSTOMER',
     @level2type = N'COLUMN', @level2name = N'CUSTOMER_MODIFIED_AT';
GO
