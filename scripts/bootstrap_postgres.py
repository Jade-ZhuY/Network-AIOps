"""Read the user-selected local container credentials without printing them."""

import argparse
import json
import re
import secrets
import subprocess
from urllib.parse import quote

import psycopg
from psycopg import sql

from app.config import ROOT


def bootstrap(container: str, database: str):
    if not re.fullmatch(r"[a-z][a-z0-9_]{1,62}", database):
        raise ValueError("Invalid database name")
    details = json.loads(
        subprocess.run(
            ["docker", "inspect", container], capture_output=True, text=True, check=True
        ).stdout
    )[0]
    env = dict(item.split("=", 1) for item in details["Config"]["Env"] if "=" in item)
    port = int(details["NetworkSettings"]["Ports"]["5432/tcp"][0]["HostPort"])
    username = "netops_state_" + secrets.token_hex(4)
    password = secrets.token_urlsafe(32)
    with psycopg.connect(
        host="127.0.0.1",
        port=port,
        user=env.get("POSTGRES_USER", "postgres"),
        password=env["POSTGRES_PASSWORD"],
        dbname=env.get("POSTGRES_DB", "postgres"),
        autocommit=True,
        connect_timeout=5,
    ) as connection:
        if connection.execute("SELECT 1 FROM pg_database WHERE datname=%s", (database,)).fetchone():
            raise ValueError("Database exists; refusing to overwrite it")
        connection.execute(
            sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
                sql.Identifier(username), sql.Literal(password)
            )
        )
        connection.execute(
            sql.SQL("CREATE DATABASE {} OWNER {}").format(
                sql.Identifier(database), sql.Identifier(username)
            )
        )
    uri = f"postgresql://{quote(username)}:{quote(password)}@127.0.0.1:{port}/{database}"
    updates = {
        "PERSISTENCE_BACKEND": "postgres",
        "CHECKPOINT_POSTGRES_URI": uri,
        "API_AUTH_TOKEN": secrets.token_urlsafe(32),
        "API_ADMIN_TOKEN": secrets.token_urlsafe(32),
        "ENABLE_DEMO_API": "false",
    }
    path = ROOT / ".env"
    lines = path.read_text(encoding="utf-8").splitlines()
    lines = [line for line in lines if line.partition("=")[0] not in updates]
    path.write_text(
        "\n".join(lines + [f"{key}={value}" for key, value in updates.items()]) + "\n",
        encoding="utf-8",
    )
    print(
        f"Created isolated PostgreSQL state database {database} on port {port}; credentials saved to ignored .env"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--container", required=True)
    parser.add_argument("--database", required=True)
    args = parser.parse_args()
    bootstrap(args.container, args.database)
