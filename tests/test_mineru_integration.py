import json
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from pymilvus import MilvusClient

from app.config import Settings
from app.main import create_app
from app.rag.mineru_client import MinerUParser, namespace_dir
from app.schemas.models import Scope
from deploy.mineru.make_fixture import create
from tests.test_sessions_api import headers

pytestmark = pytest.mark.mineru


@pytest.fixture
def remote_settings(request, tmp_path):
    if not request.config.getoption("--run-mineru"):
        pytest.skip("Use --run-mineru to upload synthetic fixtures to the configured service")
    return Settings(parsed_document_dir=tmp_path / "parsed")


def test_real_pdf_parsing_and_persistent_artifact_cache(remote_settings, tmp_path):
    source = tmp_path / "synthetic.pdf"
    create(source)
    parser = MinerUParser(remote_settings)
    document = parser.parse(source)
    assert document.parser == "mineru:4.0.12"
    assert len(document.pages) == 2
    assert [p.page_number for p in document.pages] == [1, 2]
    text = "\n".join(b.text for p in document.pages for b in p.blocks)
    assert "BGP" in text and "6.06" in text and "R3" in text
    assert not parser.last_cache_hit
    assert parser.parse(source) == document and parser.last_cache_hit
    assert (Path(document.artifacts_dir) / "middle_json.json").exists()


def test_real_markdown_uses_mineru_html_native_parser(remote_settings, tmp_path):
    source = tmp_path / "synthetic.md"
    source.write_text(
        "# BGP\n\n## Interface\n\n| Metric | Unit |\n| --- | --- |\n| Loss | % |\n",
        encoding="utf-8",
    )
    document = MinerUParser(remote_settings).parse(source)
    types = {b.block_type for p in document.pages for b in p.blocks}
    assert {"doc_title", "paragraph_title", "table"}.issubset(types)
    assert document.source_suffix == ".md" and document.submitted_suffix == ".html"
    assert all(p.page_number is None for p in document.pages)


@pytest.mark.milvus
def test_real_parser_embedding_vector_store_and_upload_delete(request, remote_settings, tmp_path):
    if not request.config.getoption("--run-milvus"):
        pytest.skip("Also pass --run-milvus for the full real parser/embedding/index test")

    root = tmp_path / "knowledge"
    root.mkdir()
    (root / "seed.md").write_text("# BGP\n\nBGP Hold Timer and interface checks.", encoding="utf-8")
    (root / "metadata.json").write_text(
        json.dumps(
            {
                "seed.md": {
                    "doc_id": "probe-seed",
                    "title": "BGP",
                    "version": "1",
                    "updated_at": "2026-10-16",
                    "access_scope": ["netops"],
                }
            }
        ),
        encoding="utf-8",
    )
    settings = remote_settings.model_copy(
        update={
            "data_backend": "mock",
            "persistence_backend": "memory",
            "knowledge_dir": root,
            "knowledge_upload_dir": tmp_path / "uploads",
            "rag_vector_backend": "milvus",
            "milvus_collection": "aiops_test_parser_" + uuid4().hex,
            "api_auth_token": SecretStr("engineer-test-token"),
            "api_admin_token": SecretStr("admin-test-token"),
            "enable_demo_api": False,
        }
    )
    control = MilvusClient(uri=settings.milvus_uri, token=settings.milvus_token.get_secret_value())
    source = tmp_path / "probe.pdf"
    create(source)
    try:
        with TestClient(create_app(settings)) as client:
            assert client.get("/health").status_code == 200
            response = client.post(
                "/api/v1/knowledge/documents",
                headers=headers(True),
                files={"file": ("probe.pdf", source.read_bytes(), "application/pdf")},
            )
            assert response.status_code == 201
            doc = response.json()
            service = client.app.state.service
            result = service.retriever.search("BGP 6.06 R3", Scope())
            assert any(c.doc_id == doc["doc_id"] and c.page in {1, 2} for c in result.citations)
            rows = [c for c in service.retriever.children if c.metadata["doc_id"] == doc["doc_id"]]
            assert rows and all(c.metadata["parser"] == "mineru:4.0.12" for c in rows)
            stored = next(settings.knowledge_upload_dir.glob(doc["doc_id"] + ".pdf"))
            cache = namespace_dir(stored, settings)
            assert cache.exists()
            assert (
                client.delete(
                    "/api/v1/knowledge/documents/" + doc["doc_id"], headers=headers(True)
                ).status_code
                == 204
            )
            assert not cache.exists()
            assert all(
                c.metadata["doc_id"] != doc["doc_id"]
                for c in service.retriever.store.load_children()
            )
    finally:
        assert settings.milvus_collection.startswith("aiops_test_parser_")
        if control.has_collection(settings.milvus_collection):
            control.drop_collection(settings.milvus_collection)
        control.close()
