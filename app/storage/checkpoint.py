from contextlib import asynccontextmanager

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool


@asynccontextmanager
async def postgres_resources(settings):
    pool = AsyncConnectionPool(
        conninfo=settings.checkpoint_postgres_uri.get_secret_value(),
        min_size=1,
        max_size=12,
        timeout=10,
        open=False,
        kwargs={
            "autocommit": True,
            "prepare_threshold": 0,
            "row_factory": dict_row,
            "connect_timeout": 5,
        },
    )
    await pool.open(wait=True)
    try:
        saver = AsyncPostgresSaver(pool)
        # Migrations are explicit (scripts.migrate), not hidden startup writes.
        async with pool.connection() as connection:
            await connection.execute("SELECT 1 FROM aiops_sessions LIMIT 1")
            await connection.execute("SELECT timezone FROM aiops_requests LIMIT 1")
            await connection.execute("SELECT 1 FROM checkpoints LIMIT 1")
        yield pool, saver
    finally:
        await pool.close()
