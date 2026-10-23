import json

import pytest
from sqlalchemy import create_engine, event

from app.config import Settings
from app.graph.workflow import WorkflowService
from app.schemas.models import Scope


def pytest_addoption(parser):
    parser.addoption(
        "--run-postgres", action="store_true", help="Durable PostgreSQL session/recovery tests"
    )
    parser.addoption(
        "--run-mysql", action="store_true", help="Read-only integration tests using local .env"
    )
    parser.addoption(
        "--run-milvus",
        action="store_true",
        help="Opt-in Milvus tests in isolated temporary collections",
    )
    parser.addoption(
        "--run-mineru", action="store_true", help="Opt-in real remote MinerU parsing tests"
    )
    parser.addoption(
        "--run-parent-mysql",
        action="store_true",
        help="Parent document persistence using configured MySQL writer",
    )


@pytest.fixture(autouse=True)
def parent_sql_engine(monkeypatch, tmp_path_factory, request):
    """Explicit SQL test database, never an application memory-parent fallback."""
    if request.node.get_closest_marker("parent_mysql"):
        yield None
        return
    from app.rag.parent_store import PARENT_SCHEMA, ParentDocumentStore

    directory = tmp_path_factory.mktemp("parent-sql")
    engine = create_engine(
        f"sqlite:///{(directory / 'parents.db').as_posix()}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def add_json_overlap(connection, _):
        connection.create_function(
            "json_overlaps",
            2,
            lambda left, right: int(bool(set(json.loads(left)) & set(json.loads(right)))),
        )

    PARENT_SCHEMA.create_all(engine)

    def factory(settings, namespace):
        return ParentDocumentStore(settings, namespace, engine=engine)

    monkeypatch.setattr("app.rag.hybrid_retrieval.ParentDocumentStore", factory)
    monkeypatch.setattr("app.rag.milvus_store.ParentDocumentStore", factory)
    yield engine
    engine.dispose()


@pytest.fixture(autouse=True)
def offline_mineru_results(monkeypatch, tmp_path, request):
    # Most regressions test routing/storage rather than remote parser quality.
    # MinerU client tests use their own MockTransport; live tests opt out explicitly.
    if request.node.get_closest_marker("mineru"):
        return
    from tests.mineru_fixtures import FakeMinerUParser

    monkeypatch.setattr("app.rag.ingestion.MinerUParser", FakeMinerUParser)


@pytest.fixture
def mysql_service(request):
    if not request.config.getoption("--run-mysql"):
        pytest.skip("Use --run-mysql to exercise the local business database")
    live = Settings(
        data_backend="mysql",
        llm_mode="mock",
        embedding_mode="mock",
        rag_vector_backend="memory",
        persistence_backend="none",
        enable_demo_api=True,
        text_to_sql_enabled=False,
    )
    instance = WorkflowService(live)
    yield instance
    instance.close()


@pytest.fixture
def settings():
    return Settings(
        _env_file=None,
        llm_mode="mock",
        data_backend="mock",
        embedding_mode="mock",
        text_to_sql_enabled=False,
    )


@pytest.fixture
def scope():
    return Scope()


@pytest.fixture
def service(settings):
    instance = WorkflowService(settings)
    yield instance
    instance.close()
