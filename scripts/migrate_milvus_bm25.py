"""Build/verify a new native-BM25 collection before switching the local configuration.

Preserves the old collection. Uses genuine MinerU cached artifacts by default.
Only child text is embedded; parent Documents continue to use MySQL.
"""

import argparse
import json
from pathlib import Path

from pymilvus import MilvusClient

from app.config import ROOT, Settings
from app.rag.chunking import chunk_parsed_document
from app.rag.document_types import validate_documents
from app.rag.hybrid_retrieval import HybridRetriever, OpenAIEmbedding
from app.rag.milvus_store import SCHEMA_DESCRIPTION, digest
from app.rag.mineru_client import MinerUParser, atomic_write
from app.schemas.models import Scope


def read_source_rows(settings):
    client = MilvusClient(
        uri=settings.milvus_uri,
        token=settings.milvus_token.get_secret_value(),
        db_name=settings.milvus_db_name,
        timeout=settings.milvus_timeout_seconds,
    )
    try:
        if not client.has_collection(settings.milvus_collection):
            return []
        description = client.describe_collection(settings.milvus_collection)
        if description.get("description") not in {
            "network-aiops-rag-chunks-v1",
            SCHEMA_DESCRIPTION,
        }:
            raise ValueError("Source is not an owned Network AIOps collection")
        client.load_collection(settings.milvus_collection)
        iterator = client.query_iterator(
            settings.milvus_collection,
            filter="",
            output_fields=["doc_id", "chunk"],
            batch_size=256,
            consistency_level="Strong",
        )
        try:
            rows = []
            while batch := iterator.next():
                rows.extend(batch)
            return rows
        finally:
            iterator.close()
    finally:
        client.close()


def build_corpus(settings, source_rows, *, allow_parse=False):
    manifest = json.loads((settings.knowledge_dir / "metadata.json").read_text(encoding="utf-8"))
    sources = {}
    for filename, metadata in manifest.items():
        path = (settings.knowledge_dir / filename).resolve()
        if not path.is_relative_to(settings.knowledge_dir.resolve()):
            raise ValueError("Source path leaves knowledge directory")
        sources[metadata["doc_id"]] = (path, metadata)
    # Do not silently lose indexed uploads when migrating an existing corpus.
    extras = {row["doc_id"] for row in source_rows} - sources.keys()
    for doc_id in extras:
        candidates = []
        for row in source_rows:
            if row["doc_id"] != doc_id:
                continue
            payload = row["chunk"]
            metadata = payload.get("metadata", payload)
            candidates.append(metadata)
        metadata = max(candidates, key=lambda item: item["updated_at"])
        path = Path(metadata["source"]).resolve()
        if not path.is_relative_to(settings.knowledge_upload_dir.resolve()):
            raise ValueError("Indexed upload source is outside the configured upload directory")
        sources[doc_id] = (
            path,
            {
                "doc_id": doc_id,
                "title": metadata["title"],
                "version": metadata["document_version"],
                "updated_at": metadata["updated_at"],
                "access_scope": metadata["access_scope"],
            },
        )
    parser = MinerUParser(settings)
    documents = {"parents": [], "children": []}
    for path, metadata in sources.values():
        parsed = parser.parse(path, cache_only=not allow_parse)
        result = chunk_parsed_document(parsed, metadata, settings=settings)
        for key in documents:
            documents[key].extend(result[key])
    validate_documents(documents)
    if not {row["doc_id"] for row in source_rows}.issubset(
        {child.metadata["doc_id"] for child in documents["children"]}
    ):
        raise ValueError("Migration would omit an indexed document; configuration was not switched")
    return documents


def switch_collection(collection):
    path = ROOT / ".env"
    lines = path.read_text(encoding="utf-8").splitlines()
    lines = [line for line in lines if not line.startswith("MILVUS_COLLECTION=")]
    atomic_write(
        path, ("\n".join(lines + ["MILVUS_COLLECTION=" + collection]) + "\n").encode("utf-8")
    )


def migrate(target_collection, *, allow_parse=False, switch=False):
    old = Settings()
    settings = old.model_copy(
        update={"milvus_collection": target_collection, "rag_vector_backend": "milvus"}
    )
    # Validate the identifier despite model_copy deliberately skipping validators.
    Settings(_env_file=None, milvus_collection=target_collection)
    rows = read_source_rows(old)
    documents = build_corpus(settings, rows, allow_parse=allow_parse)
    if settings.embedding_mode != "openai":
        raise ValueError(
            "Configure the real embedding model before migrating the application collection"
        )
    retriever = HybridRetriever(documents, settings, OpenAIEmbedding(settings), prune=True)
    try:
        retriever.store.client.flush(target_collection, timeout=60)
        children = retriever.store.load_children()
        parents = retriever.store.load_parents(children)
        validate_documents({"parents": list(parents.values()), "children": children})
        keyword_hits = retriever.store.search_bm25("BGP 接口丢包", {"netops"}, settings.rag_top_k)
        result = retriever.search("BGP 接口丢包", Scope())
        if not keyword_hits or result.status != "ok" or not result.context_documents:
            raise ValueError(
                "Native BM25/parent-context verification failed; configuration was not switched"
            )
        if any(child.metadata["doc_id"] == "restricted-sop" for child, _ in keyword_hits):
            raise ValueError("BM25 authorization verification failed")
        if old.milvus_collection != target_collection:
            after = read_source_rows(old)
            if sorted(digest(row) for row in after) != sorted(digest(row) for row in rows):
                raise ValueError(
                    "Source collection changed during migration; configuration was not switched"
                )
        report = {
            "source_collection": old.milvus_collection,
            "target_collection": target_collection,
            "source_rows_preserved": len(rows),
            "documents": len({child.metadata["doc_id"] for child in children}),
            "parent_documents": len(parents),
            "child_documents": len(children),
            "index_stats": retriever.index_stats,
            "native_bm25_hits": len(keyword_hits),
            "hybrid_status": result.status,
            "parent_contexts": len(result.context_documents),
            "embedding_model": settings.embedding_model,
            "dimension": settings.milvus_dimension,
            "parser_cache_only": not allow_parse,
            "config_switched": switch,
            "old_collection_dropped": False,
        }
        if switch:
            switch_collection(target_collection)
        return report
    finally:
        retriever.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--target-collection", default="network_aiops_chunks_hybrid")
    parser.add_argument("--allow-parse", action="store_true")
    parser.add_argument("--switch", action="store_true")
    parser.add_argument(
        "--output", type=Path, default=ROOT / "outputs" / "milvus-bm25-migration.json"
    )
    args = parser.parse_args()
    report = migrate(args.target_collection, allow_parse=args.allow_parse, switch=args.switch)
    value = json.dumps(report, ensure_ascii=False, indent=2)
    atomic_write(args.output, value.encode("utf-8"))
    print(value)


if __name__ == "__main__":
    main()
