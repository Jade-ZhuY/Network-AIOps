import re
import time
from dataclasses import dataclass

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.security.sql_guard import scoped_mysql_sql
from app.storage.fixtures import scoped_records
from app.storage.models import VIEW_SELECTS, Base


@dataclass
class Execution:
    columns: list[str]
    rows: list[dict]
    truncated: bool


class MemoryBackend:
    source = "mock-sqlite:authorized-views"

    def __init__(self, settings):
        self.settings = settings
        self.records_factory = None

    def read(self, ast, parameters, scope) -> Execution:
        # Per-query ephemeral database contains only authorized rows.
        engine = create_engine("sqlite+pysqlite:///:memory:")
        try:
            Base.metadata.create_all(engine)
            with engine.begin() as connection:
                records = scoped_records(
                    scope, self.records_factory() if self.records_factory else None
                )
                for table in Base.metadata.sorted_tables:
                    if records[table.name]:
                        connection.execute(table.insert(), records[table.name])
                for name, select in VIEW_SELECTS.items():
                    connection.exec_driver_sql(f"CREATE VIEW {name} AS {select}")
            with engine.connect() as connection:
                raw = connection.connection.driver_connection
                raw.execute("PRAGMA query_only=ON")
                deadline = time.monotonic() + self.settings.sql_timeout_ms / 1000
                raw.set_progress_handler(lambda: int(time.monotonic() >= deadline), 100)
                result = connection.execute(text(ast.sql(dialect="sqlite")), parameters)
                columns = list(result.keys())
                rows = [
                    dict(row) for row in result.mappings().fetchmany(self.settings.sql_max_rows + 1)
                ]
                return Execution(
                    columns,
                    rows[: self.settings.sql_max_rows],
                    len(rows) > self.settings.sql_max_rows,
                )
        finally:
            engine.dispose()


class MySQLBackend:
    source = "mysql:authorized-views"

    def __init__(self, settings):
        self.settings = settings
        uri = settings.mysql_readonly_uri.get_secret_value()
        if make_url(uri).drivername != "mysql+pymysql":
            raise ValueError("Expected mysql+pymysql URI")
        self.engine = create_engine(
            uri,
            pool_pre_ping=True,
            connect_args={
                "connect_timeout": 5,
                "read_timeout": max(1, settings.sql_timeout_ms // 1000 + 1),
                "write_timeout": 5,
            },
        )

    def read(self, ast, parameters, scope) -> Execution:
        secured_sql, acl_parameters = scoped_mysql_sql(ast, scope)
        with self.engine.connect() as connection:
            grants = " ".join(
                str(row[0]) for row in connection.exec_driver_sql("SHOW GRANTS FOR CURRENT_USER()")
            )
            if re.search(
                r"\b(ALL PRIVILEGES|INSERT|UPDATE|DELETE|CREATE|DROP|ALTER|EXECUTE|FILE|SUPER|GRANT OPTION)\b",
                grants,
                re.I,
            ):
                raise PermissionError("Configured MySQL account is not read-only")
            connection.commit()
            connection.exec_driver_sql("SET TRANSACTION READ ONLY")
            connection.exec_driver_sql(
                f"SET SESSION MAX_EXECUTION_TIME={self.settings.sql_timeout_ms}"
            )
            result = connection.execute(text(secured_sql), {**parameters, **acl_parameters})
            rows = [
                dict(row) for row in result.mappings().fetchmany(self.settings.sql_max_rows + 1)
            ]
            return Execution(
                list(result.keys()),
                rows[: self.settings.sql_max_rows],
                len(rows) > self.settings.sql_max_rows,
            )

    def close(self):
        self.engine.dispose()
