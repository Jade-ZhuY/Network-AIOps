from datetime import UTC, datetime

from psycopg.types.json import Jsonb

from app.storage.sessions import serialize


class DocumentStore:
    def __init__(self, sessions):
        self.sessions = sessions

    async def all(self):
        if hasattr(self.sessions, "pool"):
            async with self.sessions.pool.connection() as connection:
                cursor = await connection.execute(
                    "SELECT * FROM aiops_documents ORDER BY created_at"
                )
                return [serialize(row) for row in await cursor.fetchall()]
        return [row.copy() for row in self.sessions.documents.values()]

    async def save(self, row):
        if hasattr(self.sessions, "pool"):
            async with self.sessions.pool.connection() as connection:
                await connection.execute(
                    "INSERT INTO aiops_documents(doc_id,tenant_id,owner_id,title,filename,access_scope,status,chunk_count,error_type) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(doc_id) DO UPDATE SET status=EXCLUDED.status,chunk_count=EXCLUDED.chunk_count,error_type=EXCLUDED.error_type",
                    (
                        row["doc_id"],
                        row["tenant_id"],
                        row["owner_id"],
                        row["title"],
                        row["filename"],
                        Jsonb(row["access_scope"]),
                        row["status"],
                        row["chunk_count"],
                        row.get("error_type"),
                    ),
                )
        else:
            self.sessions.documents[row["doc_id"]] = {
                **row,
                "created_at": row.get("created_at", datetime.now(UTC).isoformat()),
            }

    async def delete(self, doc_id):
        if hasattr(self.sessions, "pool"):
            async with self.sessions.pool.connection() as connection:
                await connection.execute("DELETE FROM aiops_documents WHERE doc_id=%s", (doc_id,))
        else:
            self.sessions.documents.pop(doc_id, None)
