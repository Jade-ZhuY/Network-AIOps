"""Explicit retention operation; defaults to a non-destructive inventory."""

import argparse
import asyncio
import sys

from app.config import Settings
from app.graph.workflow import WorkflowService
from app.storage.checkpoint import postgres_resources
from app.storage.sessions import PostgresSessions


async def cleanup(days, apply):
    settings = Settings(llm_mode="mock")
    async with postgres_resources(settings) as (pool, saver):
        store = PostgresSessions(pool)
        service = WorkflowService(settings, saver, store)
        try:
            async with pool.connection() as connection:
                cursor = await connection.execute(
                    "SELECT session_id,owner_id,tenant_id,scope_hash FROM aiops_sessions WHERE updated_at < now() - (%s * interval '1 day')",
                    (days,),
                )
                rows = await cursor.fetchall()
            print(f"Expired sessions: {len(rows)}; apply={apply}; threshold={days} days")
            if apply:
                for row in rows:
                    # Use the repository lock, not a raw recursive checkpoint deletion.
                    thread_id = f"{row['tenant_id']}:{row['owner_id']}:{row['session_id']}"
                    async with pool.connection() as connection:
                        lock = await connection.execute(
                            "SELECT pg_try_advisory_lock(hashtextextended(%s,0)) AS locked",
                            (row["session_id"],),
                        )
                        if not (await lock.fetchone())["locked"]:
                            continue
                        try:
                            current = await connection.execute(
                                "SELECT 1 FROM aiops_sessions WHERE session_id=%s AND updated_at < now() - (%s * interval '1 day')",
                                (row["session_id"], days),
                            )
                            if await current.fetchone():
                                await saver.adelete_thread(thread_id)
                                await connection.execute(
                                    "DELETE FROM aiops_sessions WHERE session_id=%s",
                                    (row["session_id"],),
                                )
                        finally:
                            await connection.execute(
                                "SELECT pg_advisory_unlock(hashtextextended(%s,0))",
                                (row["session_id"],),
                            )
        finally:
            service.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.days <= 365:
        parser.error("days must be 1–365")
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(cleanup(args.days, args.apply))
