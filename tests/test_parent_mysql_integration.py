from uuid import uuid4

import pytest

from app.config import Settings
from app.rag.hybrid_retrieval import HashEmbedding, HybridRetriever
from app.rag.parent_store import ParentDocumentStore
from app.schemas.models import Scope
from tests.test_milvus_store import sample_documents

pytestmark = pytest.mark.parent_mysql


@pytest.fixture
def store(request):
    if not request.config.getoption("--run-parent-mysql"):
        pytest.skip("Use --run-parent-mysql after the explicit MySQL parent-table migration")
    settings = Settings()
    instance = ParentDocumentStore(settings, "parent-test-" + uuid4().hex)
    try:
        yield instance
    finally:
        instance.prune(set())
        instance.close()


def test_real_parent_roundtrip_upsert_acl_and_namespace(store):
    public = sample_documents("parent-test-" + uuid4().hex)["parents"][0]
    private = sample_documents("parent-test-" + uuid4().hex, access_scope=["private"])["parents"][0]
    store.put([public, private])
    assert store.get_many([public.id, private.id], {"netops"}) == {public.id: public}
    assert store.get_many([public.id], {'netops" OR true'}) == {}
    public.page_content += " UPDATED_CONTEXT"
    store.put([public])
    assert store.count() == 2
    assert store.get_many([public.id])[public.id] == public
    restarted = ParentDocumentStore(Settings(), store.namespace)
    try:
        assert restarted.get_many([public.id]) == {public.id: public}
    finally:
        restarted.close()
    store.delete_document(public.metadata["doc_id"])
    assert store.get_many([public.id]) == {}


def test_retrieval_uses_real_mysql_parent_without_parent_memory_cache(store):
    batch = sample_documents(
        "parent-test-" + uuid4().hex,
        parent_text="BGP interface checks 完整父块上下文 FULL_CONTEXT_OUTSIDE_CHILD",
    )
    settings = Settings(_env_file=None, rag_vector_backend="memory", embedding_mode="mock")
    retriever = HybridRetriever(batch, settings, HashEmbedding(), parent_store=store)
    result = retriever.search("BGP", Scope())
    assert result.status == "ok"
    assert not hasattr(retriever, "parents")
    assert "FULL_CONTEXT_OUTSIDE_CHILD" not in result.citations[0].text
    assert "FULL_CONTEXT_OUTSIDE_CHILD" in result.context_documents[0].page_content
    assert result.context_documents == batch["parents"]
    store.delete_document(batch["parents"][0].metadata["doc_id"])
    assert retriever.search("BGP", Scope()).context_documents == []
