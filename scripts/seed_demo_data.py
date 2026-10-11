"""uv run python -m scripts.seed_demo_data [--apply --uri ENV_VAR]"""

import argparse
import json
import os

from sqlalchemy import create_engine

from app.storage.fixtures import demo_records
from app.storage.models import Base


def main():
    parser = argparse.ArgumentParser(
        description="默认仅打印种子摘要；--apply 显式写入开发业务库，非会话库"
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--uri-env", default="MYSQL_SEED_URI")
    args = parser.parse_args()
    records = demo_records()
    if not args.apply:
        print(json.dumps({table: len(rows) for table, rows in records.items()}, indent=2))
        return
    uri = os.environ[args.uri_env]
    if not uri.startswith("mysql+pymysql://"):
        raise ValueError("Only a MySQL development business database is supported")
    engine = create_engine(uri)
    # DDL/views/account setup is a separate deliberate DBA step.
    with engine.begin() as connection:
        for table in Base.metadata.sorted_tables:
            if connection.execute(table.select().limit(1)).first():
                raise ValueError("Seed refuses non-empty tables; no destructive reset")
            connection.execute(table.insert(), records[table.name])
    engine.dispose()
    print("Demo business records inserted. No session/checkpoint storage created.")


if __name__ == "__main__":
    main()
