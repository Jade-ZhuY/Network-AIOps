import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.schemas.models import Scope
from app.security.auth import Principal
from app.storage.sessions import MemorySessions, SessionBusy, SessionMissing


def session_settings():
    return Settings(
        _env_file=None,
        llm_mode="mock",
        data_backend="mock",
        persistence_backend="memory",
        api_auth_token="engineer-test-token",
        api_admin_token="admin-test-token",
        enable_demo_api=False,
    )


def headers(admin=False):
    return {"Authorization": "Bearer " + ("admin-test-token" if admin else "engineer-test-token")}


def test_auth_session_chat_and_history():
    with TestClient(create_app(session_settings())) as client:
        assert client.post("/api/v1/sessions", json={}).status_code == 401
        assert client.get("/api/v1/me", headers=headers()).json()["role"] == "engineer"
        session = client.post("/api/v1/sessions", json={"title": "BGP 调查"}, headers=headers())
        assert session.status_code == 201
        sid = session.json()["session_id"]
        first = client.post(
            "/api/v1/chat",
            json={"session_id": sid, "message": "查询昨天 R2 的告警"},
            headers=headers(),
        ).json()
        assert first["status"] == "completed"
        second = client.post(
            "/api/v1/chat",
            json={"session_id": sid, "message": "那同一时间 R3 呢？"},
            headers=headers(),
        ).json()
        assert second["status"] == "completed"
        assert second["evidence"]["sql"]["queries"][0]["rows"][0]["hostname"] == "R3"
        assert second["checkpoint_saved"]
        assert not second["persistence_enabled"]  # RAM is not durable PostgreSQL.
        assert (
            len(
                client.get(f"/api/v1/sessions/{sid}/messages", headers=headers()).json()["messages"]
            )
            == 2
        )
        assert (
            client.get(f"/api/v1/requests/{first['request_id']}", headers=headers()).status_code
            == 200
        )
        assert client.get(f"/api/v1/sessions/{sid}", headers=headers(True)).status_code == 404
        assert client.get("/api/v1/admin/audit", headers=headers()).status_code == 403
        assert client.post("/api/v1/demo/analyze", json={"message": "test"}).status_code == 404
        assert client.delete(f"/api/v1/sessions/{sid}", headers=headers()).status_code == 204
        assert client.get(f"/api/v1/sessions/{sid}", headers=headers()).status_code == 404


@pytest.mark.parametrize(
    "body",
    [
        {"session_id": "x", "message": "test", "scope": {}},
        {"session_id": "x", "message": "test", "timezone": "bad/time"},
    ],
)
def test_chat_input_not_trusted(body):
    with TestClient(create_app(session_settings())) as client:
        assert client.post("/api/v1/chat", json=body, headers=headers()).status_code == 422


async def test_repository_owner_scope_and_busy():
    repo = MemorySessions()
    alice = Principal("alice", "engineer", Scope())
    bob = Principal("bob", "engineer", Scope())
    session = await repo.create(alice, "test", "UTC")
    sid = session["session_id"]
    for denied in (bob, Principal("alice", "engineer", Scope(device_ids=(2,)))):
        with pytest.raises(SessionMissing):
            await repo.get(sid, denied)
    async with repo.lock(sid, alice):
        with pytest.raises(SessionBusy):
            async with repo.lock(sid, alice):
                pass


def test_storage_failure_not_pretend_saved(monkeypatch):
    api = create_app(session_settings())
    with TestClient(api) as client:
        sid = client.post("/api/v1/sessions", json={}, headers=headers()).json()["session_id"]

        async def failed(*args, **kwargs):
            raise OSError("SECRET_DO_NOT_LOG")

        monkeypatch.setattr(api.state.service.graph.checkpointer, "aput", failed)
        result = client.post(
            "/api/v1/chat",
            json={"session_id": sid, "message": "BGP 原理是什么？"},
            headers=headers(),
        ).json()
        assert result["status"] == "failed"
        assert result["checkpoint_saved"] is False
        assert "SECRET_DO_NOT_LOG" not in str(result)
