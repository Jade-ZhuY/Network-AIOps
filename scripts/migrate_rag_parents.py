"""Create the owned MySQL parent table and optionally a narrowly scoped writer account.

Reads MYSQL_ADMIN_PASSWORD from the local ignored .env or process environment.
Never opens Milvus, parses documents, or calls embedding/LLM APIs.
"""

import argparse
import secrets

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import URL, make_url
from sqlalchemy.schema import CreateIndex, CreateTable

from app.config import ROOT, Settings
from app.rag.mineru_client import atomic_write
from app.rag.parent_store import (
    PARENT_TABLE_COMMENT,
    PARENT_TABLE_NAME,
    PARENTS,
    ParentDocumentStore,
)


class AdminSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT / ".env", extra="ignore", hide_input_in_errors=True
    )
    mysql_admin_host: str | None = None
    mysql_admin_port: int | None = None
    mysql_admin_user: str = "root"
    mysql_admin_password: SecretStr = SecretStr("")


def schema_sql():
    from sqlalchemy.dialects.mysql import dialect

    compiler = dialect()
    return (
        str(CreateTable(PARENTS).compile(dialect=compiler)).strip()
        + ";\n"
        + "\n".join(
            str(CreateIndex(index).compile(dialect=compiler)) + ";" for index in PARENTS.indexes
        )
        + "\n"
    )


def save_writer_uri(uri):
    path = ROOT / ".env"
    content = path.read_text(encoding="utf-8") if path.exists() else ""
    lines = [line for line in content.splitlines() if not line.startswith("RAG_PARENT_MYSQL_URI=")]
    atomic_write(path, ("\n".join(lines + ["RAG_PARENT_MYSQL_URI=" + uri]) + "\n").encode("utf-8"))


def migrate(*, create_account=False, account_hosts=None):
    settings, admin = Settings(), AdminSettings()
    if not admin.mysql_admin_password.get_secret_value():
        raise ValueError("Set MYSQL_ADMIN_PASSWORD in the ignored .env; no MySQL changes performed")
    if not settings.mysql_readonly_uri.get_secret_value():
        raise ValueError(
            "MYSQL_READONLY_URI is required to identify the existing application database"
        )
    target = make_url(settings.mysql_readonly_uri.get_secret_value())
    if not target.database:
        raise ValueError("No application MySQL database configured")
    if create_account and settings.rag_parent_mysql_uri.get_secret_value():
        raise ValueError("RAG_PARENT_MYSQL_URI is already set; migrate without --create-account")
    hosts = account_hosts or ["localhost", "127.0.0.1"]
    if any(not host or host == "%" for host in hosts):
        raise ValueError("Specify explicit application account hosts")
    admin_url = URL.create(
        "mysql+pymysql",
        username=admin.mysql_admin_user,
        password=admin.mysql_admin_password.get_secret_value(),
        host=admin.mysql_admin_host or target.host,
        port=admin.mysql_admin_port or target.port or 3306,
        database=target.database,
        query={"charset": "utf8mb4"},
    )
    engine = create_engine(admin_url, hide_parameters=True, connect_args={"connect_timeout": 5})
    created = False
    try:
        with engine.connect() as connection:
            inspector = inspect(connection)
            if inspector.has_table(PARENT_TABLE_NAME):
                comment = inspector.get_table_comment(PARENT_TABLE_NAME).get("text")
                columns = {column["name"] for column in inspector.get_columns(PARENT_TABLE_NAME)}
                primary = set(inspector.get_pk_constraint(PARENT_TABLE_NAME)["constrained_columns"])
                if (
                    comment != PARENT_TABLE_COMMENT
                    or not set(PARENTS.c.keys()).issubset(columns)
                    or primary != {"index_key", "parent_id"}
                ):
                    raise ValueError(
                        "Existing parent table ownership/schema mismatch; no table was overwritten"
                    )
            else:
                PARENTS.create(connection)
                connection.commit()
                created = True
            if create_account:
                username, password = "rag_parent_" + secrets.token_hex(4), secrets.token_urlsafe(36)
                created_hosts = []
                try:
                    for host in hosts:
                        connection.exec_driver_sql(
                            "CREATE USER %s@%s IDENTIFIED BY %s", (username, host, password)
                        )
                        created_hosts.append(host)
                        database = connection.dialect.identifier_preparer.quote(target.database)
                        table = connection.dialect.identifier_preparer.quote(PARENT_TABLE_NAME)
                        connection.exec_driver_sql(
                            f"GRANT SELECT, INSERT, UPDATE, DELETE ON {database}.{table} TO %s@%s",
                            (username, host),
                        )
                    connection.commit()
                    uri = URL.create(
                        "mysql+pymysql",
                        username=username,
                        password=password,
                        host=admin_url.host,
                        port=admin_url.port,
                        database=target.database,
                        query={"charset": "utf8mb4"},
                    ).render_as_string(hide_password=False)
                    save_writer_uri(uri)
                except Exception:
                    # Only compensate accounts generated in this invocation.
                    for host in created_hosts:
                        connection.exec_driver_sql("DROP USER %s@%s", (username, host))
                    connection.commit()
                    raise
        writer = Settings()
        if writer.rag_parent_mysql_uri.get_secret_value():
            store = ParentDocumentStore(writer, "migration-verification")
            try:
                store.healthcheck()
            finally:
                store.close()
        return {
            "database": target.database,
            "table": PARENT_TABLE_NAME,
            "created": created,
            "writer_configured": bool(writer.rag_parent_mysql_uri.get_secret_value()),
            "business_readonly_account_changed": False,
            "milvus_contacted": False,
        }
    finally:
        engine.dispose()


def main():
    import json

    parser = argparse.ArgumentParser()
    parser.add_argument("--print-sql", action="store_true")
    parser.add_argument("--create-account", action="store_true")
    parser.add_argument("--account-host", action="append")
    args = parser.parse_args()
    if args.print_sql:
        print(schema_sql())
        return
    try:
        result = migrate(create_account=args.create_account, account_hosts=args.account_host)
    except Exception as exc:
        # SQLAlchemy/DB-API errors may contain connection/account details. No raw traceback.
        if isinstance(exc, ValueError):
            print(str(exc))
        else:
            print(
                "MySQL parent migration failed: "
                + type(exc).__name__
                + "; check administrator credentials and privileges"
            )
        raise SystemExit(1) from None
    print(json.dumps(result))


if __name__ == "__main__":
    main()
