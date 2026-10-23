from fastapi.testclient import TestClient

from app.main import create_app
from tests.test_sessions_api import headers, session_settings


def test_upload_acl_real_retrieval_reindex_delete(tmp_path):
    settings = session_settings()
    settings.knowledge_upload_dir = tmp_path
    with TestClient(create_app(settings)) as client:
        assert (
            client.post(
                "/api/v1/knowledge/documents",
                files={"file": ("sop.md", b"# BGP\n\nNEW_SOP_EVIDENCE")},
                headers=headers(),
            ).status_code
            == 403
        )
        response = client.post(
            "/api/v1/knowledge/documents",
            files={
                "file": ("../../sop.md", "# BGP\n\nBGP 自定义接口排查 CUSTOM_EVIDENCE".encode())
            },
            headers=headers(True),
        )
        assert response.status_code == 201
        doc = response.json()
        assert doc["status"] == "ready" and doc["chunk_count"] == 1
        assert not (tmp_path.parent / "sop.md").exists()
        listed = client.get("/api/v1/knowledge/documents", headers=headers()).json()["documents"]
        assert any(row["doc_id"] == doc["doc_id"] for row in listed)
        assert all(row["doc_id"] != "restricted-sop" for row in listed)
        from app.schemas.models import Scope

        result = client.app.state.service.retriever.search(
            "BGP 自定义接口排查 CUSTOM_EVIDENCE", Scope()
        )
        assert any(citation.doc_id == doc["doc_id"] for citation in result.citations)
        result = client.app.state.service.retriever.search(
            "CUSTOM_EVIDENCE", Scope(tenant_id="other-tenant")
        )
        assert all(citation.doc_id != doc["doc_id"] for citation in result.citations)
        assert client.post("/api/v1/knowledge/reindex", headers=headers(True)).status_code == 200
        assert (
            client.delete(
                "/api/v1/knowledge/documents/" + doc["doc_id"], headers=headers(True)
            ).status_code
            == 204
        )
        assert (
            client.get(
                "/api/v1/knowledge/documents/" + doc["doc_id"], headers=headers()
            ).status_code
            == 404
        )
        assert not list(tmp_path.iterdir())


def test_invalid_uploads_and_builtin_protection(tmp_path):
    settings = session_settings()
    settings.knowledge_upload_dir = tmp_path
    with TestClient(create_app(settings)) as client:
        assert (
            client.post(
                "/api/v1/knowledge/documents",
                files={"file": ("bad.exe", b"bytes")},
                headers=headers(True),
            ).status_code
            == 415
        )
        assert (
            client.post(
                "/api/v1/knowledge/documents",
                files={"file": ("empty.txt", b"")},
                headers=headers(True),
            ).status_code
            == 413
        )
        assert (
            client.post(
                "/api/v1/knowledge/documents",
                files={"file": ("broken.pdf", b"not a PDF")},
                headers=headers(True),
            ).status_code
            == 422
        )
        assert (
            client.delete("/api/v1/knowledge/documents/sop-bgp", headers=headers(True)).status_code
            == 409
        )


def test_static_ui_and_security_headers(monkeypatch, tmp_path):
    import app.main

    dist = tmp_path / "react-dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text(
        '<!doctype html><html lang="zh-CN"><title>智能运维工作台</title>'
        '<div id="root"></div><script type="module" src="/static/assets/app.js"></script></html>',
        encoding="utf-8",
    )
    (dist / "assets" / "app.js").write_text("// React test asset", encoding="utf-8")
    monkeypatch.setattr(app.main, "FRONTEND_DIST", dist)
    with TestClient(create_app(session_settings())) as client:
        response = client.get("/")
        assert response.status_code == 200
        assert "智能运维工作台" in response.text
        assert '<div id="root">' in response.text
        assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
        assert response.headers["cache-control"] == "no-cache"
        assert "engineer-test-token" not in response.text
        asset = client.get("/static/assets/app.js")
        assert asset.status_code == 200
        assert "javascript" in asset.headers["content-type"]
        assert client.get("/static/../../.env").status_code == 404
        assert client.get("/static/app.js").status_code == 404


def test_frontend_build_missing_does_not_disable_api(monkeypatch, tmp_path):
    import app.main

    monkeypatch.setattr(app.main, "FRONTEND_DIST", tmp_path / "not-built")
    with TestClient(create_app(session_settings())) as client:
        assert client.get("/").status_code == 503
        assert client.get("/").json()["detail"] == "frontend_build_required"
        assert client.get("/openapi.json").status_code == 200
        assert client.get("/api/v1/me", headers=headers()).status_code == 200
