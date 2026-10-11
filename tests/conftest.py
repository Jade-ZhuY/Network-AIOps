import pytest

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


@pytest.fixture
def mysql_service(request):
    if not request.config.getoption("--run-mysql"):
        pytest.skip("Use --run-mysql to exercise the local business database")
    live = Settings(
        data_backend="mysql",
        llm_mode="mock",
        embedding_mode="mock",
        persistence_backend="none",
        enable_demo_api=True,
    )
    instance = WorkflowService(live)
    yield instance
    instance.close()


@pytest.fixture
def settings():
    return Settings(_env_file=None, llm_mode="mock", data_backend="mock", embedding_mode="mock")


@pytest.fixture
def scope():
    return Scope()


@pytest.fixture
def service(settings):
    instance = WorkflowService(settings)
    yield instance
    instance.close()
