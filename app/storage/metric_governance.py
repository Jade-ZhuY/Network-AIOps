"""Atomic, identity-scoped review/catalog storage in the application state database."""

import asyncio
import json
from contextlib import asynccontextmanager
from copy import deepcopy

from psycopg import Error
from psycopg.types.json import Jsonb
from psycopg_pool import PoolTimeout


class GovernanceStorageUnavailable(RuntimeError):
    pass


class GovernanceCapacityExceeded(ValueError):
    pass


MAX_DOCUMENT_BYTES = 8 * 1024 * 1024


def check_capacity(document):
    if len(json.dumps(document, ensure_ascii=False).encode()) > MAX_DOCUMENT_BYTES:
        raise GovernanceCapacityExceeded


def identity(principal):
    return principal.user_id, principal.scope.tenant_id, principal.scope_hash


def empty_document():
    return {"schema_version": 1, "reviews": {}, "metrics": {}, "feedback_cases": {}}


class MetricGovernanceStore:
    """One locked document per identity: review changes and invalidations commit together.

    No business rows are copied here. PostgreSQL survives process restarts; the
    explicit MemorySessions substitute retains its normal non-durable semantics.
    """

    def __init__(self, sessions):
        self.sessions = sessions
        if not hasattr(sessions, "pool") and not hasattr(sessions, "metric_governance"):
            sessions.metric_governance = {}
            sessions.metric_governance_lock = asyncio.Lock()

    @asynccontextmanager
    async def connection(self):
        try:
            async with self.sessions.pool.connection() as connection:
                yield connection
        except (Error, PoolTimeout):
            raise GovernanceStorageUnavailable from None

    async def read(self, principal):
        key = identity(principal)
        if hasattr(self.sessions, "pool"):
            async with self.connection() as connection:
                cursor = await connection.execute(
                    "SELECT document FROM aiops_metric_governance WHERE owner_id=%s AND tenant_id=%s AND scope_hash=%s",
                    key,
                )
                row = await cursor.fetchone()
                return deepcopy(row["document"]) if row else empty_document()
        return deepcopy(self.sessions.metric_governance.get(key, empty_document()))

    @asynccontextmanager
    async def transaction(self, principal):
        key = identity(principal)
        if hasattr(self.sessions, "pool"):
            async with self.connection() as connection, connection.transaction():
                await connection.execute(
                    "INSERT INTO aiops_metric_governance(owner_id,tenant_id,scope_hash,document) VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                    (*key, Jsonb(empty_document())),
                )
                cursor = await connection.execute(
                    "SELECT document FROM aiops_metric_governance WHERE owner_id=%s AND tenant_id=%s AND scope_hash=%s FOR UPDATE",
                    key,
                )
                document = deepcopy((await cursor.fetchone())["document"])
                yield document
                check_capacity(document)
                await connection.execute(
                    "UPDATE aiops_metric_governance SET document=%s,updated_at=now() WHERE owner_id=%s AND tenant_id=%s AND scope_hash=%s",
                    (Jsonb(document), *key),
                )
        else:
            async with self.sessions.metric_governance_lock:
                document = await self.read(principal)
                yield document
                check_capacity(document)
                self.sessions.metric_governance[key] = deepcopy(document)
