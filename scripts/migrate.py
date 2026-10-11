import asyncio
import sys

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from app.config import ROOT, Settings


async def migrate():
    settings = Settings()
    async with AsyncPostgresSaver.from_conn_string(
        settings.checkpoint_postgres_uri.get_secret_value()
    ) as saver:
        await saver.setup()
        sql = (ROOT / "app" / "storage" / "session_schema.sql").read_text(encoding="utf-8")
        # Explicit migration script only; credentials never printed.
        for statement in sql.split(";"):
            if statement.strip():
                await saver.conn.execute(statement)
    print("PostgreSQL checkpoint, session, request and document schemas ready.")


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(migrate())
