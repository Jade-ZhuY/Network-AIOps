"""Refresh only this project's development views; no business records modified."""

import os

import pymysql
from sqlalchemy.engine import make_url

from app.config import Settings
from app.storage.models import VIEW_SELECTS

if __name__ == "__main__":
    uri = make_url(Settings().mysql_readonly_uri.get_secret_value())
    if uri.database != "network_aiops_demo":
        raise ValueError("This migration is limited to the created project fixture database")
    with (
        pymysql.connect(
            host=uri.host,
            port=uri.port,
            user=os.environ.get("MYSQL_ADMIN_USER", "root"),
            password=os.environ["MYSQL_ADMIN_PASSWORD"],
            database=uri.database,
            autocommit=True,
        ) as connection,
        connection.cursor() as cursor,
    ):
        for name, select in VIEW_SELECTS.items():
            cursor.execute(f"CREATE OR REPLACE SQL SECURITY DEFINER VIEW {name} AS {select}")
            for host in ("localhost", "127.0.0.1"):
                cursor.execute(
                    f"GRANT SELECT ON `{uri.database}`.`{name}` TO %s@%s", (uri.username, host)
                )
    print(f"Updated {len(VIEW_SELECTS)} read-only views; business data unchanged.")
