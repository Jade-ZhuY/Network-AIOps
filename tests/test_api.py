import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import Settings
from app.main import create_app
from scripts.demo import QUESTIONS


def test_health_and_demo_api(settings):
    with TestClient(create_app(settings)) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["milestone"] == 8
        assert response.json()["persistence_enabled"] is False
        response = client.post("/api/v1/demo/analyze", json={"message": QUESTIONS[2]})
        assert response.status_code == 200
        assert response.json()["status"] == "completed"
        assert response.json()["report_calls"] == 1
        assert client.get("/openapi.json").status_code == 200
        assert client.post("/api/v1/sessions").status_code == 404


@pytest.mark.parametrize(
    "body",
    [
        {"message": "   "},
        {"message": "test", "timezone": "Invalid/Zone"},
        {"message": "test", "scope": {"tenant_id": "other-tenant"}},
        {"message": "test", "session_id": "someone-else"},
        {"message": "x" * 4001},
    ],
)
def test_request_scope_and_validation(settings, body):
    with TestClient(create_app(settings)) as client:
        assert client.post("/api/v1/demo/analyze", json=body).status_code == 422


def test_dependency_health_not_pretend_ready(settings, monkeypatch):
    api = create_app(settings)
    with TestClient(api) as client:

        def failed(*args):
            raise ConnectionError("secret")

        monkeypatch.setattr(api.state.service.query_service, "execute", failed)
        result = client.get("/health")
        assert result.status_code == 503
        assert "secret" not in result.text


@pytest.mark.parametrize(
    "kwargs",
    [
        {"llm_mode": "openai"},
        {"data_backend": "mysql"},
        {"embedding_mode": "openai"},
        {"sql_max_rows": 0},
        {"demo_now": "2026-10-11"},
    ],
)
def test_missing_live_config_fails_explicitly(kwargs):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **kwargs)
