from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime
from uuid import uuid4

from psycopg.types.json import Jsonb


class SessionMissing(LookupError):
    pass


class SessionBusy(RuntimeError):
    pass


def serialize(row):
    return {
        key: value.isoformat() if isinstance(value, datetime) else value
        for key, value in row.items()
    }


class PostgresSessions:
    def __init__(self, pool):
        self.pool = pool

    async def create(self, principal, title, timezone):
        async with self.pool.connection() as connection:
            cursor = await connection.execute(
                "INSERT INTO aiops_sessions(session_id,owner_id,tenant_id,scope_hash,title,timezone) VALUES (%s,%s,%s,%s,%s,%s) RETURNING *",
                (
                    str(uuid4()),
                    principal.user_id,
                    principal.scope.tenant_id,
                    principal.scope_hash,
                    title,
                    timezone,
                ),
            )
            return serialize(await cursor.fetchone())

    async def get(self, session_id, principal):
        async with self.pool.connection() as connection:
            cursor = await connection.execute(
                "SELECT * FROM aiops_sessions WHERE session_id=%s AND owner_id=%s AND tenant_id=%s AND scope_hash=%s",
                (session_id, principal.user_id, principal.scope.tenant_id, principal.scope_hash),
            )
            row = await cursor.fetchone()
            if not row:
                raise SessionMissing
            return serialize(row)

    async def list(self, principal, limit=50):
        async with self.pool.connection() as connection:
            cursor = await connection.execute(
                "SELECT * FROM aiops_sessions WHERE owner_id=%s AND tenant_id=%s AND scope_hash=%s ORDER BY updated_at DESC LIMIT %s",
                (principal.user_id, principal.scope.tenant_id, principal.scope_hash, limit),
            )
            return [serialize(row) for row in await cursor.fetchall()]

    @asynccontextmanager
    async def lock(self, session_id, principal):
        await self.get(session_id, principal)
        async with self.pool.connection() as connection:
            cursor = await connection.execute(
                "SELECT pg_try_advisory_lock(hashtextextended(%s,0)) AS locked", (session_id,)
            )
            if not (await cursor.fetchone())["locked"]:
                raise SessionBusy
            try:
                # Recheck after lock acquisition, preventing concurrent delete/use.
                yield await self.get(session_id, principal)
            finally:
                await connection.execute(
                    "SELECT pg_advisory_unlock(hashtextextended(%s,0))", (session_id,)
                )

    async def start_request(self, request_id, session_id, principal, message):
        async with self.pool.connection() as connection:
            await connection.execute(
                "INSERT INTO aiops_requests(request_id,session_id,owner_id,message) VALUES (%s,%s,%s,%s)",
                (request_id, session_id, principal.user_id, message),
            )

    async def finish_request(self, request_id, response):
        async with self.pool.connection() as connection, connection.transaction():
            cursor = await connection.execute(
                "UPDATE aiops_requests SET status=%s,response=%s,completed_at=now() WHERE request_id=%s RETURNING session_id",
                (response["status"], Jsonb(response), request_id),
            )
            row = await cursor.fetchone()
            if not row:
                raise SessionMissing
            await connection.execute(
                "UPDATE aiops_sessions SET updated_at=now() WHERE session_id=%s",
                (row["session_id"],),
            )

    async def messages(self, session_id, principal, limit=200):
        await self.get(session_id, principal)
        async with self.pool.connection() as connection:
            cursor = await connection.execute(
                "SELECT request_id,message,status,response,started_at,completed_at FROM aiops_requests WHERE session_id=%s ORDER BY started_at DESC LIMIT %s",
                (session_id, limit),
            )
            return [serialize(row) for row in reversed(await cursor.fetchall())]

    async def request(self, request_id, principal):
        async with self.pool.connection() as connection:
            cursor = await connection.execute(
                "SELECT r.* FROM aiops_requests r JOIN aiops_sessions s ON r.session_id=s.session_id WHERE r.request_id=%s AND s.owner_id=%s AND s.tenant_id=%s AND s.scope_hash=%s",
                (request_id, principal.user_id, principal.scope.tenant_id, principal.scope_hash),
            )
            row = await cursor.fetchone()
            if not row:
                raise SessionMissing
            return serialize(row)

    async def delete(self, session_id, principal):
        await self.get(session_id, principal)
        async with self.pool.connection() as connection:
            await connection.execute(
                "DELETE FROM aiops_sessions WHERE session_id=%s", (session_id,)
            )

    async def audit(self, principal, limit=50):
        async with self.pool.connection() as connection:
            cursor = await connection.execute(
                "SELECT r.request_id,r.session_id,r.status,r.started_at,r.completed_at,r.response->>'route' AS route,r.response->>'trace_id' AS trace_id FROM aiops_requests r JOIN aiops_sessions s ON r.session_id=s.session_id WHERE s.owner_id=%s AND s.tenant_id=%s AND s.scope_hash=%s ORDER BY r.started_at DESC LIMIT %s",
                (principal.user_id, principal.scope.tenant_id, principal.scope_hash, limit),
            )
            return [serialize(row) for row in await cursor.fetchall()]


class MemorySessions:
    """Explicit test/development substitute. Does not claim restart durability."""

    def __init__(self):
        self.sessions, self.requests, self.documents = {}, {}, {}
        self.busy = set()

    async def create(self, principal, title, timezone):
        now = datetime.now(UTC).isoformat()
        row = dict(
            session_id=str(uuid4()),
            owner_id=principal.user_id,
            tenant_id=principal.scope.tenant_id,
            scope_hash=principal.scope_hash,
            title=title,
            timezone=timezone,
            created_at=now,
            updated_at=now,
        )
        self.sessions[row["session_id"]] = row
        return row.copy()

    async def get(self, session_id, principal):
        row = self.sessions.get(session_id)
        if not row or (row["owner_id"], row["tenant_id"], row["scope_hash"]) != (
            principal.user_id,
            principal.scope.tenant_id,
            principal.scope_hash,
        ):
            raise SessionMissing
        return row.copy()

    async def list(self, principal, limit=50):
        result = []
        for session_id in self.sessions:
            with suppress(SessionMissing):
                result.append(await self.get(session_id, principal))
        return sorted(result, key=lambda row: row["updated_at"], reverse=True)[:limit]

    @asynccontextmanager
    async def lock(self, session_id, principal):
        row = await self.get(session_id, principal)
        if session_id in self.busy:
            raise SessionBusy
        self.busy.add(session_id)
        try:
            yield row
        finally:
            self.busy.remove(session_id)

    async def start_request(self, request_id, session_id, principal, message):
        self.requests[request_id] = dict(
            request_id=request_id,
            session_id=session_id,
            owner_id=principal.user_id,
            message=message,
            status="running",
            response=None,
            started_at=datetime.now(UTC).isoformat(),
            completed_at=None,
        )

    async def finish_request(self, request_id, response):
        row = self.requests[request_id]
        row.update(
            status=response["status"], response=response, completed_at=datetime.now(UTC).isoformat()
        )
        self.sessions[row["session_id"]]["updated_at"] = row["completed_at"]

    async def messages(self, session_id, principal, limit=200):
        await self.get(session_id, principal)
        return [row.copy() for row in self.requests.values() if row["session_id"] == session_id][
            -limit:
        ]

    async def request(self, request_id, principal):
        row = self.requests.get(request_id)
        if not row:
            raise SessionMissing
        await self.get(row["session_id"], principal)
        return row.copy()

    async def delete(self, session_id, principal):
        await self.get(session_id, principal)
        self.sessions.pop(session_id)
        self.requests = {
            key: value for key, value in self.requests.items() if value["session_id"] != session_id
        }

    async def audit(self, principal, limit=50):
        allowed = {row["session_id"] for row in await self.list(principal, 200)}
        return [
            dict(
                request_id=row["request_id"],
                session_id=row["session_id"],
                status=row["status"],
                started_at=row["started_at"],
                completed_at=row["completed_at"],
                route=(row["response"] or {}).get("route"),
                trace_id=(row["response"] or {}).get("trace_id"),
            )
            for row in reversed(list(self.requests.values()))
            if row["session_id"] in allowed
        ][:limit]
