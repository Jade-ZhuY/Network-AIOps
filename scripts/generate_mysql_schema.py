from sqlalchemy.dialects import mysql
from sqlalchemy.schema import CreateIndex, CreateTable

from app.config import ROOT
from app.storage.models import VIEW_SELECTS, Base


def schema_sql():
    statements = [
        "-- Generated from app/storage/models.py; MySQL 8, UTC timestamps.\n-- Run in a dedicated development BUSINESS database; no checkpoint tables.\nSET time_zone = '+00:00';"
    ]
    for table in Base.metadata.sorted_tables:
        statements.append(str(CreateTable(table).compile(dialect=mysql.dialect())).strip() + ";")
        for index in sorted(table.indexes, key=lambda item: item.name):
            statements.append(str(CreateIndex(index).compile(dialect=mysql.dialect())) + ";")
    for name, select in VIEW_SELECTS.items():
        statements.append(f"CREATE SQL SECURITY DEFINER VIEW {name} AS {select};")
    statements.append(
        "-- Provision a netops_ro account separately with SELECT on these four views ONLY.\n-- No base-table privileges, no root_cause/resolution field in views.\n-- Credentials are not stored here."
    )
    return "\n\n".join(statements) + "\n"


if __name__ == "__main__":
    (ROOT / "scripts" / "init_mysql.sql").write_text(schema_sql(), encoding="utf-8")
