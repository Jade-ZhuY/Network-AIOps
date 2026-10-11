import asyncio
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException

from app.rag.hybrid_retrieval import HybridRetriever
from app.rag.ingestion import load_documents, parse_document
from app.storage.documents import DocumentStore


class KnowledgeManager:
    def __init__(self, service, sessions, settings):
        self.service, self.settings = service, settings
        self.store = DocumentStore(sessions)
        self.lock = asyncio.Lock()

    def path(self, filename):
        root = self.settings.knowledge_upload_dir.resolve()
        path = (root / filename).resolve()
        if not path.is_relative_to(root):
            raise ValueError("Document path outside upload directory")
        return path

    @staticmethod
    def groups(principal):
        return {
            f"tenant:{principal.scope.tenant_id}:{group}"
            for group in principal.scope.knowledge_groups
        }

    async def list(self, principal):
        rows = []
        seed = {}
        for chunk in load_documents(self.settings.knowledge_dir):
            if set(chunk.access_scope).intersection(principal.scope.knowledge_groups):
                seed.setdefault(
                    chunk.doc_id,
                    dict(
                        doc_id=chunk.doc_id,
                        title=chunk.title,
                        status="ready",
                        builtin=True,
                        chunk_count=0,
                        created_at=chunk.updated_at,
                    ),
                )
                seed[chunk.doc_id]["chunk_count"] += 1
        rows.extend(seed.values())
        rows.extend(
            {**row, "builtin": False}
            for row in await self.store.all()
            if row["tenant_id"] == principal.scope.tenant_id
            and set(row["access_scope"]).intersection(self.groups(principal))
        )
        return rows

    async def get(self, doc_id, principal):
        row = next((row for row in await self.list(principal) if row["doc_id"] == doc_id), None)
        if not row:
            raise HTTPException(status_code=404, detail="Document not found")
        return row

    async def rebuild(self):
        async with self.lock:
            chunks = load_documents(self.settings.knowledge_dir)
            for row in await self.store.all():
                if row["status"] == "ready":
                    path = self.path(row["filename"])
                    if path.is_file():
                        metadata = {
                            "doc_id": row["doc_id"],
                            "title": row["title"],
                            "version": "1",
                            "updated_at": row["created_at"],
                            "access_scope": row["access_scope"],
                        }
                        chunks.extend(await asyncio.to_thread(parse_document, path, metadata))
            retriever = await asyncio.to_thread(
                HybridRetriever, chunks, self.settings, self.service.retriever.embedding
            )
            self.service.retriever = self.service.runtime.retriever = retriever

    async def upload(self, filename, title, content, principal):
        suffix = Path(filename).suffix.lower()
        if suffix not in (".md", ".txt", ".pdf"):
            raise HTTPException(
                status_code=415, detail="Supported files: Markdown, UTF-8 text, PDF"
            )
        if not content or len(content) > self.settings.upload_max_bytes:
            raise HTTPException(status_code=413, detail="Empty file or upload size exceeded")
        if not principal.scope.knowledge_groups:
            raise HTTPException(status_code=403, detail="No writable knowledge scope")
        doc_id = "upload-" + uuid4().hex
        stored_filename = doc_id + suffix
        self.settings.knowledge_upload_dir.mkdir(parents=True, exist_ok=True)
        path = self.path(stored_filename)
        path.write_bytes(content)
        row = dict(
            doc_id=doc_id,
            tenant_id=principal.scope.tenant_id,
            owner_id=principal.user_id,
            title=title or Path(filename).stem[:100],
            filename=stored_filename,
            access_scope=sorted(self.groups(principal)),
            status="indexing",
            chunk_count=0,
            created_at=datetime.now(UTC).isoformat(),
            error_type=None,
        )
        await self.store.save(row)
        try:
            metadata = {
                "doc_id": doc_id,
                "title": row["title"],
                "version": "1",
                "updated_at": row["created_at"],
                "access_scope": row["access_scope"],
            }
            chunks = await asyncio.to_thread(parse_document, path, metadata)
            if not chunks or len(chunks) > 500:
                raise ValueError("Document has no text or exceeds 500 chunks")
            row.update(status="ready", chunk_count=len(chunks))
            await self.store.save(row)
            await self.rebuild()
            return {**row, "builtin": False}
        except Exception as exc:
            row.update(status="failed", error_type=type(exc).__name__)
            await self.store.save(row)
            raise HTTPException(
                status_code=422,
                detail={"doc_id": doc_id, "status": "failed", "error_type": type(exc).__name__},
            ) from None

    async def remove(self, doc_id, principal):
        row = await self.get(doc_id, principal)
        if row["builtin"]:
            raise HTTPException(
                status_code=409, detail="Built-in demonstration references are read-only"
            )
        path = self.path(row["filename"])
        await self.store.delete(doc_id)
        path.unlink(missing_ok=True)
        await self.rebuild()
