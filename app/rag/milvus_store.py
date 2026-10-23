"""Milvus-native dense + BM25 indexes over child Documents, with MySQL parents."""

import hashlib
import json
import math

from langchain_core.documents import Document

from app.rag.chunking import chunker_config
from app.rag.document_types import validate_documents
from app.rag.mineru_client import ADAPTER_VERSION
from app.rag.parent_store import ParentDocumentStore

SCHEMA_DESCRIPTION = "network-aiops-rag-hybrid-v2"
PIPELINE_VERSION = "mineru-v1:langchain-native-documents-token-v2:milvus-bm25-v1:redaction-v1"
ANALYZER_PARAMS = {"tokenizer": "jieba", "filter": ["lowercase", "removepunct"]}


def search_text(document):
    return document.page_content + "\n" + " / ".join(document.metadata["section_path"])


def digest(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def document_namespace(settings):
    return digest(
        {
            "pipeline": PIPELINE_VERSION,
            "chunker": chunker_config(settings),
            "parser_service": settings.mineru_api_url.strip().rstrip("/"),
            "parser_version": settings.mineru_expected_version,
            "parser_adapter": ADAPTER_VERSION,
            "parser_tier": settings.mineru_tier,
            "parser_ocr_mode": settings.mineru_ocr_mode,
            "embedding_mode": settings.embedding_mode,
            "model": settings.embedding_model
            if settings.embedding_mode == "openai"
            else "mock-hash-embedding",
            "endpoint": settings.embedding_base_url.strip().rstrip("/")
            if settings.embedding_mode == "openai"
            else "mock",
            "dimension": settings.milvus_dimension
            if settings.rag_vector_backend == "milvus"
            else 256,
            "analyzer": ANALYZER_PARAMS,
            "bm25_k1": settings.milvus_bm25_k1,
            "bm25_b": settings.milvus_bm25_b,
        }
    )


class MilvusDocumentStore:
    def __init__(self, settings, client=None):
        from pymilvus import DataType, Function, FunctionType, MilvusClient

        self.collection = settings.milvus_collection
        self.dimension = settings.milvus_dimension
        self.timeout = settings.milvus_timeout_seconds
        self.bm25_k1 = settings.milvus_bm25_k1
        self.bm25_b = settings.milvus_bm25_b
        self.index_key = document_namespace(settings)
        self.parent_store = ParentDocumentStore(settings, self.index_key)
        self.client = client
        try:
            if self.client is None:
                self.client = MilvusClient(
                    uri=settings.milvus_uri,
                    token=settings.milvus_token.get_secret_value(),
                    db_name=settings.milvus_db_name,
                    timeout=self.timeout,
                )
            if not self.client.has_collection(self.collection, timeout=self.timeout):
                schema = MilvusClient.create_schema(
                    auto_id=False, enable_dynamic_field=False, description=SCHEMA_DESCRIPTION
                )
                schema.add_field("id", DataType.VARCHAR, is_primary=True, max_length=64)
                schema.add_field("chunk_id", DataType.VARCHAR, max_length=512)
                schema.add_field("doc_id", DataType.VARCHAR, max_length=512)
                schema.add_field("index_key", DataType.VARCHAR, max_length=64)
                schema.add_field("fingerprint", DataType.VARCHAR, max_length=64)
                schema.add_field("content_hash", DataType.VARCHAR, max_length=64)
                schema.add_field(
                    "access_scope",
                    DataType.ARRAY,
                    element_type=DataType.VARCHAR,
                    max_capacity=256,
                    max_length=256,
                )
                schema.add_field("chunk", DataType.JSON)
                schema.add_field("vector", DataType.FLOAT_VECTOR, dim=self.dimension)
                schema.add_field(
                    "search_text",
                    DataType.VARCHAR,
                    max_length=65535,
                    enable_analyzer=True,
                    analyzer_params=ANALYZER_PARAMS,
                )
                schema.add_field("bm25_vector", DataType.SPARSE_FLOAT_VECTOR)
                schema.add_function(
                    Function(
                        name="child_text_bm25",
                        function_type=FunctionType.BM25,
                        input_field_names=["search_text"],
                        output_field_names=["bm25_vector"],
                    )
                )
                indexes = MilvusClient.prepare_index_params()
                indexes.add_index(field_name="vector", index_type="AUTOINDEX", metric_type="COSINE")
                indexes.add_index(
                    field_name="bm25_vector",
                    index_type="SPARSE_INVERTED_INDEX",
                    metric_type="BM25",
                    params={
                        "inverted_index_algo": "DAAT_MAXSCORE",
                        "bm25_k1": self.bm25_k1,
                        "bm25_b": self.bm25_b,
                    },
                )
                # Never drop/recreate a collection. Concurrent creators may win the race.
                try:
                    self.client.create_collection(
                        self.collection,
                        schema=schema,
                        index_params=indexes,
                        consistency_level="Strong",
                        timeout=self.timeout,
                    )
                except Exception:
                    if not self.client.has_collection(self.collection, timeout=self.timeout):
                        raise
            description = self.client.describe_collection(self.collection, timeout=self.timeout)
            fields = {field["name"]: field for field in description["fields"]}
            required = {
                "id",
                "chunk_id",
                "doc_id",
                "index_key",
                "fingerprint",
                "content_hash",
                "access_scope",
                "chunk",
                "vector",
                "search_text",
                "bm25_vector",
            }
            if description.get("description") != SCHEMA_DESCRIPTION or not required.issubset(
                fields
            ):
                raise ValueError(
                    "Milvus collection is not an owned BM25 hybrid index; choose a new collection (the dense-only collection is preserved)"
                )
            if int(fields["vector"]["params"]["dim"]) != self.dimension:
                raise ValueError(
                    "Milvus vector dimension mismatch; use a new collection for this embedding model"
                )
            if not fields["id"].get("is_primary"):
                raise ValueError("Invalid Milvus primary key")
            if fields["bm25_vector"].get("type") != DataType.SPARSE_FLOAT_VECTOR:
                raise ValueError("Expected a sparse BM25 vector field")
            text_params = fields["search_text"].get("params", {})
            analyzer = text_params.get("analyzer_params")
            if isinstance(analyzer, str):
                analyzer = json.loads(analyzer)
            enabled = str(text_params.get("enable_analyzer", False)).lower() == "true"
            if not enabled or analyzer != ANALYZER_PARAMS:
                raise ValueError("Milvus text analyzer mismatch; choose a new collection")
            functions = description.get("functions", [])
            if not any(
                function.get("name") == "child_text_bm25"
                and function.get("type") == FunctionType.BM25
                and function.get("input_field_names") == ["search_text"]
                and function.get("output_field_names") == ["bm25_vector"]
                for function in functions
            ):
                raise ValueError("Milvus BM25 function is missing or mismatched")
            dense_index = self.client.describe_index(
                self.collection, index_name="vector", timeout=self.timeout
            )
            sparse_index = self.client.describe_index(
                self.collection, index_name="bm25_vector", timeout=self.timeout
            )
            if (
                dense_index.get("metric_type") != "COSINE"
                or sparse_index.get("metric_type") != "BM25"
            ):
                raise ValueError("Milvus dense/BM25 metric mismatch")
            if (
                sparse_index.get("index_type") != "SPARSE_INVERTED_INDEX"
                or float(sparse_index.get("bm25_k1", -1)) != self.bm25_k1
                or float(sparse_index.get("bm25_b", -1)) != self.bm25_b
            ):
                raise ValueError("Milvus BM25 index parameters mismatch; choose a new collection")
            self.client.load_collection(self.collection, timeout=self.timeout)
        except Exception:
            if self.client is not None:
                self.client.close()
            self.parent_store.close()
            raise

    def record_id(self, chunk):
        return digest([self.index_key, chunk.id])

    def _filter(self, groups=None):
        expression = f"index_key == {json.dumps(self.index_key)}"
        if groups is not None:
            # JSON escaping protects identifiers containing quotes/backslashes.
            expression += f" and ARRAY_CONTAINS_ANY(access_scope, {json.dumps(sorted(groups), ensure_ascii=False)})"
        return expression

    def _scan(self, expression, fields):
        iterator = self.client.query_iterator(
            self.collection,
            filter=expression,
            output_fields=fields,
            batch_size=256,
            consistency_level="Strong",
            timeout=self.timeout,
        )
        try:
            rows = []
            while batch := iterator.next():
                rows.extend(batch)
            return rows
        finally:
            iterator.close()

    def load_children(self, groups=None):
        if groups is not None and not groups:
            return []
        chunks = []
        for row in self._scan(self._filter(groups), ["chunk"]):
            document = Document.model_validate(row["chunk"])
            if not document.id or document.metadata.get("chunk_type") != "child":
                raise ValueError("Dense index must contain only child Documents")
            chunks.append(document)
        return sorted(chunks, key=lambda chunk: chunk.id)

    def load_parents(self, children, groups=None):
        return self.parent_store.get_many(
            [child.metadata["parent_id"] for child in children], groups
        )

    def sync(self, documents, embedding, *, prune=False):
        validate_documents(documents)
        chunks = documents["children"]
        if any(len(search_text(child).encode("utf-8")) > 65535 for child in chunks):
            raise ValueError("Child BM25 input exceeds the Milvus VARCHAR byte limit")
        desired = {self.record_id(chunk): chunk for chunk in chunks}
        existing = {}
        ids = list(desired)
        for start in range(0, len(ids), 256):
            rows = self.client.get(
                self.collection,
                ids[start : start + 256],
                output_fields=["id", "fingerprint", "content_hash"],
                consistency_level="Strong",
                timeout=self.timeout,
            )
            existing.update({row["id"]: row for row in rows})
        pending = [
            (key, chunk)
            for key, chunk in desired.items()
            if existing.get(key, {}).get("fingerprint") != digest(chunk.model_dump(mode="json"))
        ]
        new_texts = [
            (key, chunk)
            for key, chunk in pending
            if existing.get(key, {}).get("content_hash") != digest(chunk.page_content)
        ]
        new_ids = {key for key, _ in new_texts}
        cached_ids = [key for key, _ in pending if key not in new_ids]
        cached_vectors = {}
        for start in range(0, len(cached_ids), 256):
            cached_vectors.update(
                {
                    row["id"]: row["vector"]
                    for row in self.client.get(
                        self.collection,
                        cached_ids[start : start + 256],
                        output_fields=["id", "vector"],
                        consistency_level="Strong",
                        timeout=self.timeout,
                    )
                }
            )
        # All remote embeddings are computed and validated before any index mutation.
        vectors = (
            embedding.embed([chunk.page_content for _, chunk in new_texts]) if new_texts else []
        )
        if len(vectors) != len(new_texts):
            raise ValueError("Embedding response count mismatch")
        by_id = {key: vector for (key, _), vector in zip(new_texts, vectors, strict=True)}
        by_id.update(cached_vectors)
        if any(key not in by_id for key, _ in pending):
            raise ValueError("Cached Milvus vector changed during indexing; retry synchronization")
        for vector in by_id.values():
            if (
                len(vector) != self.dimension
                or not all(math.isfinite(v) for v in vector)
                or sum(v * v for v in vector) == 0
            ):
                raise ValueError("Embedding vector dimension or values are invalid for Milvus")
        records = [
            {
                "id": key,
                "chunk_id": chunk.id,
                "doc_id": chunk.metadata["doc_id"],
                "index_key": self.index_key,
                "fingerprint": digest(chunk.model_dump(mode="json")),
                "content_hash": digest(chunk.page_content),
                "access_scope": chunk.metadata["access_scope"],
                "chunk": chunk.model_dump(mode="json"),
                "vector": by_id[key],
                "search_text": search_text(chunk),
            }
            for key, chunk in pending
        ]
        # Parent text is stored separately, never embedded or copied into child metadata.
        # Write parents before references; an interrupted upsert can only leave orphans.
        self.parent_store.put(documents["parents"])
        for start in range(0, len(records), 128):
            self.client.upsert(self.collection, records[start : start + 128], timeout=self.timeout)
        stale = []
        doc_ids = sorted({parent.metadata["doc_id"] for parent in documents["parents"]})
        if prune or doc_ids:
            expression = self._filter()
            if not prune:
                # Each supplied document is a complete parse, even when only a subset
                # of the corpus is being synced (e.g. startup seeds or one upload).
                expression += f" and doc_id in {json.dumps(doc_ids, ensure_ascii=False)}"
            stale = [
                row["id"] for row in self._scan(expression, ["id"]) if row["id"] not in desired
            ]
            for start in range(0, len(stale), 256):
                self.client.delete(
                    self.collection, ids=stale[start : start + 256], timeout=self.timeout
                )
            active = self.load_children()
            self.parent_store.prune(
                {child.metadata["parent_id"] for child in active}, None if prune else set(doc_ids)
            )
        return {
            "embedded_chunks": len(new_texts),
            "reused_chunks": len(desired) - len(new_texts),
            "deleted_chunks": len(stale),
        }

    def search(self, vector, groups, limit):
        if not groups:
            return []
        if len(vector) != self.dimension or not all(math.isfinite(v) for v in vector):
            raise ValueError("Query embedding dimension or values are invalid for Milvus")
        results = self.client.search(
            self.collection,
            data=[vector],
            anns_field="vector",
            filter=self._filter(groups),
            output_fields=["chunk_id"],
            limit=limit,
            search_params={"metric_type": "COSINE", "params": {}},
            consistency_level="Strong",
            timeout=self.timeout,
        )
        return [hit["entity"]["chunk_id"] for hit in results[0]]

    @staticmethod
    def _documents(results, groups):
        matches = []
        for hit in results[0]:
            document = Document.model_validate(hit["entity"]["chunk"])
            if document.metadata.get("chunk_type") != "child":
                raise ValueError("Search returned a non-child Document")
            if set(document.metadata["access_scope"]).intersection(groups):
                matches.append((document, float(hit["distance"])))
        return matches

    def search_bm25(self, question, groups, limit):
        if not groups or not question.strip():
            return []
        results = self.client.search(
            self.collection,
            data=[question],
            anns_field="bm25_vector",
            filter=self._filter(groups),
            output_fields=["chunk"],
            limit=limit,
            search_params={"metric_type": "BM25", "params": {}},
            consistency_level="Strong",
            timeout=self.timeout,
        )
        return self._documents(results, groups)

    def hybrid_search(self, question, vector, groups, limit):
        from pymilvus import AnnSearchRequest, RRFRanker

        if not groups or not question.strip():
            return []
        if len(vector) != self.dimension or not all(math.isfinite(v) for v in vector):
            raise ValueError("Query embedding dimension or values are invalid for Milvus")
        expression = self._filter(groups)
        requests = [
            AnnSearchRequest(
                data=[vector],
                anns_field="vector",
                expr=expression,
                limit=limit,
                param={"metric_type": "COSINE", "params": {}},
            ),
            AnnSearchRequest(
                data=[question],
                anns_field="bm25_vector",
                expr=expression,
                limit=limit,
                param={"metric_type": "BM25", "params": {}},
            ),
        ]
        results = self.client.hybrid_search(
            self.collection,
            reqs=requests,
            ranker=RRFRanker(k=60),
            limit=limit * 2,
            output_fields=["chunk"],
            consistency_level="Strong",
            timeout=self.timeout,
        )
        return self._documents(results, groups)

    def delete_document(self, doc_id):
        # Remove every embedding-version namespace belonging to this document.
        self.client.delete(
            self.collection, filter=f"doc_id == {json.dumps(doc_id)}", timeout=self.timeout
        )
        self.parent_store.delete_document(doc_id)

    def healthcheck(self):
        self.parent_store.healthcheck()
        self.client.query(
            self.collection,
            filter=self._filter(),
            output_fields=["id"],
            limit=1,
            consistency_level="Strong",
            timeout=self.timeout,
        )

    def close(self):
        try:
            self.client.close()
        finally:
            self.parent_store.close()
