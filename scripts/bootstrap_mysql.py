"""Create a NEW local business fixture database and a scoped read-only account."""

import argparse
import os
import re
import secrets

import pymysql
from sqlalchemy import create_engine
from sqlalchemy.engine import URL

from app.config import ROOT
from app.storage.fixtures import demo_records
from app.storage.models import VIEW_SELECTS, Base


def bootstrap(database: str):
    if not re.fullmatch(r"[a-z][a-z0-9_]{1,62}", database):
        raise ValueError("Invalid database identifier")
    host = os.environ.get("MYSQL_ADMIN_HOST", "127.0.0.1")
    port = int(os.environ.get("MYSQL_ADMIN_PORT", "3306"))
    user = os.environ.get("MYSQL_ADMIN_USER", "root")
    password = os.environ["MYSQL_ADMIN_PASSWORD"]
    readonly_user = "netops_ro_" + secrets.token_hex(4)
    readonly_password = secrets.token_urlsafe(32)
    admin = pymysql.connect(
        host=host, port=port, user=user, password=password, connect_timeout=5, autocommit=True
    )
    try:
        with admin.cursor() as cursor:
            cursor.execute(
                "SELECT SCHEMA_NAME FROM INFORMATION_SCHEMA.SCHEMATA WHERE SCHEMA_NAME=%s",
                (database,),
            )
            if cursor.fetchone():
                raise ValueError("Database already exists; refusing to reuse or overwrite it")
            cursor.execute(
                f"CREATE DATABASE `{database}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
        uri = URL.create(
            "mysql+pymysql",
            username=user,
            password=password,
            host=host,
            port=port,
            database=database,
        )
        engine = create_engine(uri)
        try:
            Base.metadata.create_all(engine)
            with engine.begin() as connection:
                records = demo_records()
                for table in Base.metadata.sorted_tables:
                    connection.execute(table.insert(), records[table.name])
                for name, select in VIEW_SELECTS.items():
                    connection.exec_driver_sql(
                        f"CREATE SQL SECURITY DEFINER VIEW {name} AS {select}"
                    )
        finally:
            engine.dispose()
        with admin.cursor() as cursor:
            for account_host in ("localhost", "127.0.0.1"):
                cursor.execute(
                    "CREATE USER %s@%s IDENTIFIED BY %s",
                    (readonly_user, account_host, readonly_password),
                )
                for view in VIEW_SELECTS:
                    cursor.execute(
                        f"GRANT SELECT ON `{database}`.`{view}` TO %s@%s",
                        (readonly_user, account_host),
                    )
        readonly_uri = URL.create(
            "mysql+pymysql",
            username=readonly_user,
            password=readonly_password,
            host=host,
            port=port,
            database=database,
        ).render_as_string(hide_password=False)
        path = ROOT / ".env"
        lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
        lines = [
            line for line in lines if not line.startswith(("DATA_BACKEND=", "MYSQL_READONLY_URI="))
        ]
        path.write_text(
            "\n".join(lines + ["DATA_BACKEND=mysql", f"MYSQL_READONLY_URI={readonly_uri}"]) + "\n",
            encoding="utf-8",
        )
        print(
            f"Created business database: {database}; tables=6; scenarios=3; read-only user={readonly_user}"
        )
        print(
            "Application credentials saved to ignored .env. No admin password saved; no checkpoints."
        )
    finally:
        admin.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", required=True)
    args = parser.parse_args()
    bootstrap(args.database)
