import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pymilvus import MilvusClient

from app.config import Settings
from app.main import create_app
from app.rag.hybrid_retrieval import HashEmbedding, HybridRetriever
from app.rag.milvus_store import MilvusDocumentStore
from app.schemas.models import Scope
from tests.test_milvus_store import combine, sample_documents
from tests.test_sessions_api import headers

pytestmark = pytest.mark.milvus


@pytest.fixture
def milvus_settings(request, tmp_path):
    if not request.config.getoption("--run-milvus"):
        pytest.skip("Use --run-milvus for isolated collection integration tests")
    settings = Settings(
        _env_file=None,
        llm_mode="mock",
        data_backend="mock",
        embedding_mode="mock",
        rag_vector_backend="milvus",
        milvus_dimension=256,
        milvus_uri=os.getenv("MILVUS_TEST_URI", "http://127.0.0.1:19530"),
        milvus_token=os.getenv("MILVUS_TEST_TOKEN", ""),
        milvus_collection="aiops_test_" + uuid4().hex,
        persistence_backend="memory",
        api_auth_token="engineer-test-token",
        api_admin_token="admin-test-token",
        knowledge_upload_dir=tmp_path,
        enable_demo_api=False,
    )
    client = MilvusClient(uri=settings.milvus_uri, token=settings.milvus_token.get_secret_value())
    try:
        yield settings
    finally:
        # Only the UUID-named collection created by this test is removed.
        assert settings.milvus_collection.startswith("aiops_test_")
        if client.has_collection(settings.milvus_collection):
            client.drop_collection(settings.milvus_collection)
        client.close()


class CountingEmbedding(HashEmbedding):
    def __init__(self):
        self.texts = []

    def embed(self, texts):
        self.texts.extend(texts)
        return super().embed(texts)


def test_persistence_incremental_updates_acl_and_delete(milvus_settings):
    settings = milvus_settings
    embedding = CountingEmbedding()
    public = sample_documents()
    private = sample_documents("private", access_scope=["tenant:private-tenant:netops"])
    first = HybridRetriever(combine(public, private), settings, embedding)
    try:
        assert first.index_stats["embedded_chunks"] == 2 and len(embedding.texts) == 2
        assert first.vectors == []
        assert first.search("BGP", Scope()).citations[0].doc_id == "sample"
        assert {c.metadata["doc_id"] for c in first.store.load_children({"netops"})} == {"sample"}
    finally:
        first.close()
    embedding.texts.clear()
    restarted = HybridRetriever(public, settings, embedding)
    try:
        assert restarted.index_stats["embedded_chunks"] == 0 and embedding.texts == []
        assert {c.metadata["doc_id"] for c in restarted.children} == {"sample", "private"}
        updated = sample_documents(
            child_id="sample:child-2", text="BGP Hold Timer interface checks"
        )
        reader = HybridRetriever(
            combine(updated, private), settings, embedding, store=restarted.store, prune=True
        )
        assert reader.index_stats == {"embedded_chunks": 1, "reused_chunks": 1, "deleted_chunks": 1}
        assert embedding.texts == [updated["children"][0].page_content]
        assert {c.id for c in restarted.store.load_children()} == {
            "sample:child-2",
            "private:child-1",
        }
        assert restarted.search("BGP", Scope(knowledge_groups=())).status == "no_evidence"
        assert (
            restarted.search("BGP", Scope(knowledge_groups=('netops" or true',))).status
            == "no_evidence"
        )
        restarted.store.delete_document("sample")
        assert restarted.search("BGP", Scope()).status == "no_evidence"
        assert (
            restarted.search("BGP", Scope(tenant_id="private-tenant")).citations[0].doc_id
            == "private"
        )
    finally:
        restarted.close()


def test_real_milvus_upload_reindex_delete_and_health(milvus_settings, monkeypatch):
    settings = milvus_settings
    with TestClient(create_app(settings)) as client:
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["vector_backend"] == "milvus"
        service = client.app.state.service
        old_ids = {chunk.id for chunk in service.retriever.children}
        response = client.post(
            "/api/v1/knowledge/documents",
            headers=headers(True),
            files={"file": ("probe.md", "# BGP\n\nBGP MILVUS_UPLOAD_PROBE 接口排查".encode())},
        )
        assert response.status_code == 201
        doc_id = response.json()["doc_id"]
        assert service.retriever.index_stats["embedded_chunks"] == 1
        assert old_ids.issubset({chunk.id for chunk in service.retriever.children})
        result = service.retriever.search("BGP MILVUS_UPLOAD_PROBE", Scope())
        assert any(c.doc_id == doc_id for c in result.citations)
        result = service.retriever.search("MILVUS_UPLOAD_PROBE", Scope(tenant_id="other"))
        assert all(c.doc_id != doc_id for c in result.citations)
        assert client.post("/api/v1/knowledge/reindex", headers=headers(True)).status_code == 200
        assert service.retriever.index_stats["embedded_chunks"] == 0
        assert (
            client.delete(
                f"/api/v1/knowledge/documents/{doc_id}", headers=headers(True)
            ).status_code
            == 204
        )
        assert all(
            chunk.metadata["doc_id"] != doc_id for chunk in service.retriever.store.load_children()
        )
        assert service.retriever.index_stats["embedded_chunks"] == 0

        def failed():
            raise ConnectionError("private connection detail")

        monkeypatch.setattr(service.retriever.store, "healthcheck", failed)
        health = client.get("/health")
        assert health.status_code == 503
        assert "private connection detail" not in health.text


def test_schema_dimension_mismatch_does_not_destroy_data(milvus_settings):
    store = MilvusDocumentStore(milvus_settings)
    try:
        store.sync(sample_documents(), HashEmbedding())
        wrong = milvus_settings.model_copy(update={"milvus_dimension": 1024})
        with pytest.raises(ValueError, match="dimension mismatch"):
            MilvusDocumentStore(wrong)
        assert len(store.load_children()) == 1
    finally:
        store.close()


def test_parent_context_survives_client_restart_and_acl(milvus_settings, tmp_path):
    from app.rag.chunking import chunk_parsed_document
    from app.rag.mineru_client import normalize_result
    from tests.mineru_fixtures import result_payload

    settings = milvus_settings.model_copy(
        update={
            "rag_parent_chunk_size": 300,
            "rag_parent_chunk_overlap": 60,
            "rag_child_chunk_size": 100,
            "rag_child_chunk_overlap": 20,
        }
    )
    payload = result_payload(
        [
            {
                "page_idx": 0,
                "blocks": [
                    {
                        "type": "doc_title",
                        "level": 1,
                        "content": [{"type": "text", "content": "BGP"}],
                    },
                    {
                        "type": "text",
                        "content": [
                            {"type": "text", "content": "NEEDLE " + ("filler " * 300) + "TAIL"}
                        ],
                    },
                ],
            }
        ]
    )
    d = normalize_result(payload, tmp_path / "sample.pdf", "sha", ".pdf", "4.0.12", tmp_path)
    metadata = {
        "doc_id": "parent-fixture",
        "title": "BGP",
        "version": "1",
        "updated_at": "2026-10-18",
        "access_scope": ["netops"],
    }
    chunks = chunk_parsed_document(d, metadata, settings=settings)
    first = HybridRetriever(chunks, settings, HashEmbedding())
    parents = first.store.load_parents(first.children)
    assert len(parents) > 1
    first.close()
    restarted = HybridRetriever(chunks, settings, HashEmbedding())
    try:
        assert restarted.index_stats["embedded_chunks"] == 0
        assert restarted.store.load_parents(restarted.children) == parents
        assert all(isinstance(c.metadata["section_path"], list) for c in restarted.children)
        result = restarted.search("NEEDLE", Scope())
        assert result.citations and result.citations[0].parent_id in parents
        assert (
            result.citations[0].parent_text == parents[result.citations[0].parent_id].page_content
        )
        assert (
            restarted.search("NEEDLE", Scope(knowledge_groups=("other-team",))).status
            == "no_evidence"
        )
    finally:
        restarted.close()


def test_native_bm25_chinese_english_acl_and_delete(milvus_settings):
    from tests.test_milvus_store import combine

    public = sample_documents("bm25-public", text="BGP 接口丢包 光模块故障")
    private = sample_documents(
        "bm25-private", text="BGP 光模块故障 " * 20, access_scope=["private-team"]
    )
    other = sample_documents(
        "bm25-other", text="OSPF area mismatch", section_path=["OSPF"], section="OSPF"
    )
    store = MilvusDocumentStore(milvus_settings)
    try:
        store.sync(combine(public, private, other), HashEmbedding())
        chinese = store.search_bm25("光模块故障", {"netops"}, 1)
        assert [doc.metadata["doc_id"] for doc, _ in chinese] == ["bm25-public"]
        english = store.search_bm25("bgp", {"netops"}, 8)
        assert [doc.metadata["doc_id"] for doc, _ in english] == ["bm25-public"]
        assert store.search_bm25("光模块故障", {'netops" OR true'}, 8) == []
        store.delete_document("bm25-public")
        assert store.search_bm25("光模块故障", {"netops"}, 8) == []
    finally:
        store.close()


def test_native_bm25_updates_title_without_reembedding_child(milvus_settings):
    embedding = CountingEmbedding()
    store = MilvusDocumentStore(milvus_settings)
    try:
        first = sample_documents(
            "bm25-title",
            text="interface checks",
            section_path=["LegacyTitle"],
            section="LegacyTitle",
        )
        store.sync(first, embedding)
        assert store.search_bm25("LegacyTitle", {"netops"}, 8)
        embedding.texts.clear()
        changed = sample_documents(
            "bm25-title",
            text="interface checks",
            section_path=["CurrentTitle"],
            section="CurrentTitle",
        )
        stats = store.sync(changed, embedding)
        assert stats["embedded_chunks"] == 0 and embedding.texts == []
        assert store.search_bm25("CurrentTitle", {"netops"}, 8)
        assert store.search_bm25("LegacyTitle", {"netops"}, 8) == []
    finally:
        store.close()
