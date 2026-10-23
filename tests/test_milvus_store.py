import json
from unittest.mock import MagicMock

import pytest
from langchain_core.documents import Document
from pymilvus import DataType, FunctionType

from app.config import Settings
from app.rag.document_types import validate_documents
from app.rag.hybrid_retrieval import HashEmbedding, HybridRetriever
from app.rag.milvus_store import ANALYZER_PARAMS, SCHEMA_DESCRIPTION, MilvusDocumentStore
from app.schemas.models import Scope


def sample_documents(
    doc_id="sample", *, text="BGP interface checks", parent_text=None, child_id=None, **changes
):
    metadata = {
        "doc_id": doc_id,
        "title": "BGP",
        "section": "Checks",
        "section_path": ["BGP", "Checks"],
        "page": None,
        "source": "fixture.md",
        "document_version": "1",
        "updated_at": "2026-10-18",
        "access_scope": ["netops"],
        "parser": "mineru:4.0.12",
        "chunker_version": "test-native-v2",
        "section_block_ids": ["p0:b1"],
        "parent_index": 0,
    }
    metadata.update(changes)
    metadata["access_scope"] = list(metadata["access_scope"])
    parent = Document(
        id=doc_id + ":parent-1",
        page_content=parent_text or text,
        metadata={**metadata, "chunk_type": "parent"},
    )
    child = Document(
        id=child_id or doc_id + ":child-1",
        page_content=text,
        metadata={**metadata, "chunk_type": "child", "parent_id": parent.id, "child_index": 0},
    )
    return {"parents": [parent], "children": [child]}


def combine(*batches):
    return {
        key: [doc for batch in batches for doc in batch[key]] for key in ("parents", "children")
    }


def mock_store(tmp_path):
    settings = Settings(
        _env_file=None,
        rag_vector_backend="milvus",
        milvus_dimension=256,
    )
    client, rows = MagicMock(), {}
    client.has_collection.return_value = True
    client.describe_collection.return_value = {
        "description": SCHEMA_DESCRIPTION,
        "fields": [
            {"name": name, "params": {"dim": 256}, "is_primary": name == "id"}
            for name in [
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
            ]
        ],
        "functions": [
            {
                "name": "child_text_bm25",
                "type": FunctionType.BM25,
                "input_field_names": ["search_text"],
                "output_field_names": ["bm25_vector"],
            }
        ],
    }
    fields = {field["name"]: field for field in client.describe_collection.return_value["fields"]}
    fields["search_text"]["params"] = {
        "max_length": 65535,
        "enable_analyzer": True,
        "analyzer_params": ANALYZER_PARAMS,
    }
    fields["bm25_vector"]["type"] = DataType.SPARSE_FLOAT_VECTOR
    client.describe_index.side_effect = lambda *args, **kwargs: (
        {"metric_type": "COSINE"}
        if kwargs["index_name"] == "vector"
        else {
            "metric_type": "BM25",
            "index_type": "SPARSE_INVERTED_INDEX",
            "bm25_k1": "1.2",
            "bm25_b": "0.75",
        }
    )
    client.get.side_effect = lambda collection, ids, **kw: [rows[key] for key in ids if key in rows]

    def upsert(collection, records, **kw):
        rows.update({row["id"]: row for row in records})

    def scan(collection, *, filter, output_fields, **kw):
        selected = list(rows.values())
        if "doc_id in " in filter:
            docs = json.loads(filter.split("doc_id in ", 1)[1])
            selected = [row for row in selected if row["doc_id"] in docs]
        iterator = MagicMock()
        iterator.next.side_effect = [
            [{key: row[key] for key in output_fields} for row in selected],
            [],
        ]
        return iterator

    def delete(collection, ids=None, filter=None, **kw):
        keys = ids or [
            key
            for key, row in rows.items()
            if row["doc_id"] == json.loads(filter.split("doc_id == ")[1])
        ]
        for key in keys:
            rows.pop(key, None)

    client.upsert.side_effect = upsert
    client.query_iterator.side_effect = scan
    client.delete.side_effect = delete
    client.hybrid_search.side_effect = lambda *args, **kwargs: [
        [{"entity": {"chunk": row["chunk"]}, "distance": 0.03} for row in rows.values()]
    ]
    return settings, client, MilvusDocumentStore(settings, client=client)


def test_unchanged_documents_do_not_call_embedding_or_upsert(tmp_path):
    _, client, store = mock_store(tmp_path)
    batch = sample_documents()
    store.sync(batch, HashEmbedding())
    client.upsert.reset_mock()
    embedding = MagicMock()
    assert store.sync(batch, embedding) == {
        "embedded_chunks": 0,
        "reused_chunks": 1,
        "deleted_chunks": 0,
    }
    embedding.embed.assert_not_called()
    client.upsert.assert_not_called()


def test_native_child_records_and_separate_parent_store_survive_restart(tmp_path):
    settings, client, store = mock_store(tmp_path)
    batch = sample_documents(parent_text="BGP interface checks. FULL_PARENT_CONTEXT")
    embedding = MagicMock(wraps=HashEmbedding())
    store.sync(batch, embedding)
    embedding.embed.assert_called_once_with([batch["children"][0].page_content])
    row = client.upsert.call_args.args[1][0]
    assert row["chunk"]["page_content"] == batch["children"][0].page_content
    assert "FULL_PARENT_CONTEXT" not in json.dumps(row)
    assert row["chunk"]["metadata"]["chunk_type"] == "child"
    restarted = MilvusDocumentStore(settings, client=client)
    children = restarted.load_children({"netops"})
    parents = restarted.load_parents(children, {"netops"})
    assert children == batch["children"]
    assert list(parents.values()) == batch["parents"]
    validate_documents({"parents": list(parents.values()), "children": children})
    assert restarted.load_parents(children, {"other-team"}) == {}


def test_embedding_failure_happens_before_index_or_parent_mutation(tmp_path):
    _, client, store = mock_store(tmp_path)
    embedding = MagicMock()
    embedding.embed.side_effect = RuntimeError("embedding unavailable")
    with pytest.raises(RuntimeError):
        store.sync(sample_documents(), embedding, prune=True)
    client.delete.assert_not_called()
    client.upsert.assert_not_called()
    assert store.parent_store.count() == 0


def test_metadata_only_updates_reuse_vector(tmp_path):
    _, client, store = mock_store(tmp_path)
    store.sync(sample_documents(), HashEmbedding())
    embedding = MagicMock()
    changed = sample_documents(title="Updated title", access_scope=["private-team"])
    assert store.sync(changed, embedding)["embedded_chunks"] == 0
    embedding.embed.assert_not_called()
    assert client.upsert.call_args.args[1][0]["access_scope"] == ["private-team"]


def test_existing_foreign_collection_is_never_recreated(tmp_path):
    settings, client, store = mock_store(tmp_path)
    client.describe_collection.return_value["description"] = "another application"
    with pytest.raises(ValueError, match="not an owned"):
        MilvusDocumentStore(settings, client=client)
    client.create_collection.assert_not_called()
    client.drop_collection.assert_not_called()
    store.close()


def test_acl_is_in_search_filter_before_top_k(tmp_path):
    _, client, store = mock_store(tmp_path)
    client.search.return_value = [[{"entity": {"chunk_id": "allowed"}}]]
    group = 'team" or true'
    assert store.search([0.1] * 256, {group}, 8) == ["allowed"]
    arguments = client.search.call_args.kwargs
    assert arguments["filter"] == store._filter({group})
    assert "ARRAY_CONTAINS_ANY" in arguments["filter"] and arguments["limit"] == 8
    assert store.search([0.1] * 256, set(), 8) == []


def test_retrieval_refreshes_children_and_expands_parent(tmp_path):
    settings, _, store = mock_store(tmp_path)
    batch = sample_documents(parent_text="BGP interface checks FULL_PARENT_CONTEXT")
    child = batch["children"][0]
    store.search = MagicMock(return_value=[child.id])
    retriever = HybridRetriever(batch, settings, HashEmbedding(), store=store)
    result = retriever.search("BGP", Scope())
    assert result.status == "ok" and result.citations[0].text == child.page_content
    assert result.context_documents == batch["parents"]
    assert "FULL_PARENT_CONTEXT" in result.summary
    assert "milvus" in result.data_source and retriever.vectors == []
    store.delete_document(child.metadata["doc_id"])
    assert retriever.search("BGP", Scope()).status == "no_evidence"
    assert store.parent_store.count() == 0


def test_bm25_uses_raw_query_and_database_acl_filter(tmp_path):
    _, client, store = mock_store(tmp_path)
    child = sample_documents()["children"][0]
    client.search.return_value = [
        [{"entity": {"chunk": child.model_dump(mode="json")}, "distance": 1.2}]
    ]
    result = store.search_bm25("BGP interface", {"netops"}, 8)
    assert result == [(child, 1.2)]
    kwargs = client.search.call_args.kwargs
    assert kwargs["data"] == ["BGP interface"] and kwargs["anns_field"] == "bm25_vector"
    assert kwargs["filter"] == store._filter({"netops"})
    assert kwargs["search_params"]["metric_type"] == "BM25"


def test_native_hybrid_search_filters_both_routes_and_fuses_in_milvus(tmp_path):
    settings, client, store = mock_store(tmp_path)
    batch = sample_documents()
    retriever = HybridRetriever(batch, settings, HashEmbedding(), store=store)
    store.load_children = MagicMock(
        side_effect=AssertionError("Query must not download the full corpus")
    )
    result = retriever.search("BGP interface", Scope())
    assert result.status == "ok"
    kwargs = client.hybrid_search.call_args.kwargs
    assert len(kwargs["reqs"]) == 2
    for request in kwargs["reqs"]:
        assert request.expr == store._filter({"netops", "tenant:demo-tenant:netops"})
    assert {request.anns_field for request in kwargs["reqs"]} == {"vector", "bm25_vector"}
    assert kwargs["ranker"].dict()["strategy"] == "rrf"
    assert retriever.corpus_tokens == []


def test_bm25_parameter_drift_requires_a_new_collection(tmp_path):
    settings, client, _ = mock_store(tmp_path)
    with pytest.raises(ValueError, match="parameters mismatch"):
        MilvusDocumentStore(settings.model_copy(update={"milvus_bm25_b": 0.5}), client=client)


def test_partial_document_sync_prunes_only_that_documents_stale_children(tmp_path):
    _, _, store = mock_store(tmp_path)
    store.sync(combine(sample_documents(), sample_documents("other")), HashEmbedding())
    changed = sample_documents(child_id="sample:child-new", text="BGP changed")
    assert store.sync(changed, HashEmbedding())["deleted_chunks"] == 1
    assert {child.id for child in store.load_children()} == {"sample:child-new", "other:child-1"}


def test_parent_documents_never_accepted_as_dense_input(tmp_path):
    _, client, store = mock_store(tmp_path)
    batch = sample_documents()
    with pytest.raises(ValueError):
        store.sync({"parents": [], "children": batch["parents"]}, MagicMock())
    client.upsert.assert_not_called()
