import json
from unittest.mock import MagicMock

import pytest
from langchain_core.documents import Document
from sqlalchemy import event
from sqlalchemy.dialects.mysql import dialect
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.schema import CreateTable

from app.config import Settings
from app.rag.hybrid_retrieval import HashEmbedding, HybridRetriever
from app.rag.parent_store import PARENTS, ParentDocumentStore
from app.schemas.models import Scope
from scripts.migrate_rag_parents import schema_sql
from tests.test_milvus_store import sample_documents


def parent_store(engine, namespace="fixture"):
    return ParentDocumentStore(Settings(_env_file=None), namespace, engine=engine)


def test_runtime_requires_mysql_writer_and_has_no_implicit_fallback():
    with pytest.raises(ValueError, match="RAG_PARENT_MYSQL_URI"):
        ParentDocumentStore(Settings(_env_file=None), "fixture")
    for uri in ("sqlite:///parents.db", "postgresql://user:password@localhost/db"):
        with pytest.raises(ValueError, match="mysql\\+pymysql"):
            ParentDocumentStore(Settings(_env_file=None, rag_parent_mysql_uri=uri), "fixture")


def test_runtime_rejects_business_readonly_account_reuse():
    uri = "mysql+pymysql://reader:password@127.0.0.1:3306/db"
    with pytest.raises(ValueError, match="separate"):
        ParentDocumentStore(
            Settings(_env_file=None, mysql_readonly_uri=uri, rag_parent_mysql_uri=uri), "fixture"
        )


def test_mysql_schema_is_separate_non_vector_parent_table():
    ddl = str(CreateTable(PARENTS).compile(dialect=dialect()))
    assert "page_content LONGTEXT" in ddl and "metadata JSON" in ddl
    assert "PRIMARY KEY (index_key, parent_id)" in ddl
    assert "vector" not in PARENTS.c
    assert "network-aiops-rag-parents-v1" in ddl
    assert "CREATE INDEX ix_rag_parent_documents_doc_id" in schema_sql()


def test_roundtrip_and_restart_reconstruct_native_document(parent_sql_engine):
    original = sample_documents(parent_text="BGP interface checks FULL_CONTEXT")["parents"][0]
    writer = parent_store(parent_sql_engine)
    writer.put([original])
    restarted = parent_store(parent_sql_engine)
    loaded = restarted.get_many([original.id], {"netops"})[original.id]
    assert isinstance(loaded, Document) and loaded == original
    assert restarted.count() == 1
    writer.put([original])
    assert writer.count() == 1


def test_acl_is_bound_in_sql_before_documents_are_read(parent_sql_engine):
    store = parent_store(parent_sql_engine)
    public = sample_documents()["parents"][0]
    private = sample_documents("private", access_scope=["private-team"])["parents"][0]
    store.put([public, private])
    statements = []

    def capture(connection, cursor, statement, parameters, context, executemany):
        statements.append((statement, parameters))

    event.listen(parent_sql_engine, "before_cursor_execute", capture)
    try:
        assert set(store.get_many([public.id, private.id], {"netops"})) == {public.id}
        assert store.get_many([public.id, private.id], {'netops" OR true'}) == {}
    finally:
        event.remove(parent_sql_engine, "before_cursor_execute", capture)
    assert all("json_overlaps" in sql for sql, _ in statements)
    assert all('netops" OR true' not in sql for sql, _ in statements)
    assert store.get_many([public.id], set()) == {}


def test_namespace_scope_prune_and_delete(parent_sql_engine):
    first, other_version = (
        parent_store(parent_sql_engine, "v1"),
        parent_store(parent_sql_engine, "v2"),
    )
    a = sample_documents()["parents"][0]
    b = sample_documents("other")["parents"][0]
    first.put([a, b])
    other_version.put([a])
    first.prune(set(), {"sample"})
    assert first.get_many([a.id]) == {}
    assert first.get_many([b.id]) == {b.id: b}
    assert other_version.get_many([a.id]) == {a.id: a}
    first.delete_document("sample")
    assert other_version.count() == 0 and first.count() == 1


def test_input_validation_precedes_all_writes(parent_sql_engine):
    store = parent_store(parent_sql_engine)
    good = sample_documents()["parents"][0]
    invalid = sample_documents("bad")["parents"][0]
    invalid.metadata["chunk_type"] = "child"
    with pytest.raises(ValueError):
        store.put([good, invalid])
    assert store.count() == 0
    invalid = good.model_copy(deep=True)
    invalid.metadata["business"] = {"value": float("nan")}
    with pytest.raises(ValueError):
        store.put([invalid])
    assert store.count() == 0


def test_failed_batch_rolls_back_parent_transaction(parent_sql_engine):
    store = parent_store(parent_sql_engine)
    first, second = sample_documents()["parents"][0], sample_documents("second")["parents"][0]
    inserts = 0

    def fail_second(connection, cursor, statement, parameters, context, executemany):
        nonlocal inserts
        if statement.startswith("INSERT"):
            inserts += 1
            if inserts == 2:
                raise RuntimeError("synthetic write failure")

    event.listen(parent_sql_engine, "before_cursor_execute", fail_second)
    try:
        with pytest.raises(RuntimeError):
            store.put([first, second])
    finally:
        event.remove(parent_sql_engine, "before_cursor_execute", fail_second)
    assert store.count() == 0


def test_retriever_has_no_parent_cache_and_reads_updates_from_sql(parent_sql_engine):
    batch = sample_documents()
    settings = Settings(_env_file=None)
    store = parent_store(parent_sql_engine)
    retriever = HybridRetriever(batch, settings, HashEmbedding(), parent_store=store)
    assert not hasattr(retriever, "parents")
    updated = batch["parents"][0].model_copy(
        update={"page_content": "BGP interface checks UPDATED_IN_DATABASE"}
    )
    store.put([updated])
    assert "UPDATED_IN_DATABASE" in retriever.search("BGP", Scope()).summary
    PARENTS.drop(parent_sql_engine)
    with pytest.raises(SQLAlchemyError):
        retriever.search("BGP", Scope())


def test_parent_store_never_has_a_local_json_directory(parent_sql_engine):
    store = parent_store(parent_sql_engine)
    assert not hasattr(store, "root") and not hasattr(store, "directory")
    assert not hasattr(Settings(_env_file=None), "parent_document_dir")
    assert store.get_many([], {"netops"}) == {}


def test_parent_json_metadata_remains_serializable(parent_sql_engine):
    store = parent_store(parent_sql_engine)
    parent = sample_documents()["parents"][0]
    parent.metadata["business"] = {"vendor": "fixture", "tags": ["BGP", "checks"]}
    store.put([parent])
    loaded = store.get_many([parent.id])[parent.id]
    assert (
        json.loads(loaded.model_dump_json())["metadata"]["business"] == parent.metadata["business"]
    )


def test_parent_engine_is_not_created_when_config_is_missing(monkeypatch):
    create = MagicMock()
    monkeypatch.setattr("app.rag.parent_store.create_engine", create)
    with pytest.raises(ValueError):
        ParentDocumentStore(Settings(_env_file=None), "fixture")
    create.assert_not_called()
