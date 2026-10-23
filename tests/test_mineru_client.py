import copy
import time
from pathlib import Path

import httpx
import pytest

from app.config import Settings
from app.rag.chunking import chunk_parsed_document
from app.rag.mineru_client import (
    MinerUError,
    MinerUParser,
    namespace_dir,
    normalize_result,
    purge_parsed_artifacts,
    same_origin_url,
)
from tests.mineru_fixtures import result_payload

KEY = "TEST_MINERU_KEY_1234567890123456789012345"


def settings_for(tmp_path, **kwargs):
    return Settings(
        _env_file=None,
        mineru_api_url="http://fixture:18000",
        mineru_api_key=KEY,
        parsed_document_dir=tmp_path / "parsed",
        mineru_poll_interval_seconds=0.001,
        **kwargs,
    )


def test_remote_pdf_artifacts_and_cache_reuse(tmp_path):
    source = tmp_path / "scan.pdf"
    source.write_bytes(b"synthetic PDF bytes handled only by fake remote API")
    requests = []

    def handle(request):
        requests.append(request)
        assert request.headers["authorization"] == "Bearer " + KEY
        assert request.url.path == "/v1/file_parse"
        assert request.url.params["tier"] == "standard"
        assert request.url.params.get_list("output_formats") == [
            "markdown",
            "middle_json",
            "structured_content",
        ]
        assert b'name="files"' in request.read()
        return httpx.Response(200, json=result_payload())

    parser = MinerUParser(settings_for(tmp_path), transport=httpx.MockTransport(handle))
    document = parser.parse(source)
    assert not parser.last_cache_hit
    assert document.parser == "mineru:4.0.12"
    assert document.pages[0].page_number == 1
    assert document.pages[0].blocks[0].bbox == (0.1, 0.1, 0.9, 0.2)
    assert parser.parse(source) == document
    assert parser.last_cache_hit and len(requests) == 1
    root = Path(document.artifacts_dir)
    assert {
        "response.json",
        "middle_json.json",
        "structured_content.json",
        "document.md",
        "manifest.json",
    }.issubset({p.name for p in root.iterdir()})
    assert all(KEY not in p.read_text(encoding="utf-8") for p in root.iterdir())
    source.write_bytes(b"changed source")
    parser.parse(source)
    assert len(requests) == 2
    purge_parsed_artifacts(source, parser.settings)
    assert not namespace_dir(source, parser.settings).exists()


def test_cache_only_parse_never_submits_a_remote_job(tmp_path):
    source = tmp_path / "scan.pdf"
    source.write_bytes(b"fixture")
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(200, json=result_payload())

    parser = MinerUParser(settings_for(tmp_path), transport=httpx.MockTransport(handle))
    with pytest.raises(MinerUError, match="cache-only"):
        parser.parse(source, cache_only=True)
    assert not requests
    expected = parser.parse(source)
    assert parser.parse(source, cache_only=True) == expected
    assert len(requests) == 1


@pytest.mark.parametrize("suffix", [".md", ".txt"])
def test_text_is_wrapped_and_still_parsed_remotely(tmp_path, suffix):
    source = tmp_path / ("native" + suffix)
    source.write_text("# BGP\n\nhello <script>fixture</script>", encoding="utf-8")

    def handle(request):
        assert request.url.params["tier"] == "flash"
        body = request.read()
        assert b'filename="native.html"' in body
        assert b"&lt;script&gt;" in body
        return httpx.Response(200, json=result_payload(physical=False))

    document = MinerUParser(settings_for(tmp_path), transport=httpx.MockTransport(handle)).parse(
        source
    )
    assert document.source_suffix == suffix and document.submitted_suffix == ".html"
    assert document.pages[0].page_number is None


def test_async_polling_and_result_fetch(tmp_path):
    source = tmp_path / "scan.pdf"
    source.write_bytes(b"fixture")
    paths = []

    def handle(request):
        paths.append(request.url.path)
        if request.method == "POST":
            return httpx.Response(
                202,
                json={
                    "task_id": "job",
                    "status_url": "/v1/tasks/job",
                    "result_url": "/v1/tasks/job/result",
                },
            )
        if request.url.path.endswith("/result"):
            return httpx.Response(200, json=result_payload())
        return httpx.Response(200, json={"status": "running" if len(paths) == 2 else "completed"})

    document = MinerUParser(settings_for(tmp_path), transport=httpx.MockTransport(handle)).parse(
        source
    )
    assert document.pages
    assert paths == ["/v1/file_parse", "/v1/tasks/job", "/v1/tasks/job", "/v1/tasks/job/result"]
    assert not (Path(document.artifacts_dir) / "pending.json").exists()


@pytest.mark.parametrize(
    "url",
    [
        "http://other:18000/task",
        "http://fixture:18001/task",
        "https://fixture:18000/task",
        "http://user:pass@fixture:18000/task",
    ],
)
def test_polling_rejects_other_origins(url):
    with pytest.raises(MinerUError):
        same_origin_url("http://fixture:18000", url)


@pytest.mark.parametrize(
    "case", ["partial", "failed", "bad_schema", "bad_version", "incomplete", "bad_page"]
)
def test_invalid_remote_results_never_become_valid_cache(tmp_path, case):
    source = tmp_path / "scan.pdf"
    source.write_bytes(b"fixture")
    result = result_payload()
    if case in {"partial", "failed"}:
        result["status"] = case
    elif case == "bad_schema":
        result["files"][0]["content"]["middle_json"]["schema"] = "other"
    elif case == "bad_version":
        result["files"][0]["content"]["middle_json"]["metadata"]["producer"]["version"] = "other"
    elif case == "incomplete":
        result["files"][0]["content"]["middle_json"]["is_full_document"] = False
    else:
        result["files"][0]["content"]["middle_json"]["pages"][0]["page_idx"] = -1
    parser = MinerUParser(
        settings_for(tmp_path),
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=result)),
    )
    with pytest.raises(MinerUError):
        parser.parse(source)
    assert not list((tmp_path / "parsed").rglob("manifest.json"))


@pytest.mark.parametrize("code", [401, 403, 500, 302])
def test_http_failures_do_not_fall_back_to_old_pdf_parser(tmp_path, code):
    source = tmp_path / "scan.pdf"
    source.write_bytes(b"not a locally parseable PDF")
    parser = MinerUParser(
        settings_for(tmp_path),
        transport=httpx.MockTransport(lambda r: httpx.Response(code, text=KEY)),
    )
    with pytest.raises(MinerUError) as error:
        parser.parse(source)
    assert KEY not in str(error.value)
    assert not list((tmp_path / "parsed").rglob("manifest.json"))


def test_block_contract_preserves_table_and_physical_page_locator(tmp_path):
    payload = result_payload(
        [
            {
                "page_idx": 4,
                "blocks": [
                    {
                        "type": "chapter_title",
                        "level": 2,
                        "content": [{"type": "text", "content": "BGP"}],
                    },
                    {
                        "type": "table",
                        "bbox": [0, 0, 1, 1],
                        "content": [
                            {
                                "type": "table_body",
                                "content": "<table><tr><td>6.06%</td></tr></table>",
                            }
                        ],
                    },
                    {"type": "equation", "content": [{"type": "latex", "content": "x=1"}]},
                ],
            }
        ]
    )
    document = normalize_result(payload, tmp_path / "scan.pdf", "sha", ".pdf", "4.0.12", tmp_path)
    assert document.pages[0].page_number == 5
    assert document.pages[0].blocks[1].block_type == "table"
    assert "6.06%" in document.pages[0].blocks[1].text
    assert document.pages[0].blocks[2].text == "x=1"
    metadata = {
        "doc_id": "fixture",
        "title": "BGP",
        "version": "1",
        "updated_at": "now",
        "access_scope": ["netops"],
    }
    chunks = chunk_parsed_document(document, metadata)
    child = chunks["children"][0]
    assert child.metadata["page"] == 5
    assert child.metadata["section"] == "BGP"
    assert child.metadata["parser"] == "mineru:4.0.12"


def test_invalid_cache_is_reparsed_by_mineru(tmp_path):
    source = tmp_path / "scan.pdf"
    source.write_bytes(b"fixture")
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(200, json=result_payload())

    parser = MinerUParser(settings_for(tmp_path), transport=httpx.MockTransport(handle))
    document = parser.parse(source)
    (Path(document.artifacts_dir) / "middle_json.json").write_text("corrupt")
    parser.parse(source)
    assert len(calls) == 2 and not parser.last_cache_hit


def test_schema_objects_are_preserved_without_mutation(tmp_path):
    payload = result_payload()
    original = copy.deepcopy(payload)
    normalize_result(payload, tmp_path / "a.pdf", "sha", ".pdf", "4.0.12", tmp_path)
    assert payload == original


def test_total_timeout_is_bounded_without_retrying_upload(tmp_path, monkeypatch):
    source = tmp_path / "scan.pdf"
    source.write_bytes(b"fixture")
    calls = []
    clock = [0.0]
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])

    def handle(request):
        calls.append(request)
        if request.method == "POST":
            return httpx.Response(
                202, json={"status_url": "/v1/tasks/job", "result_url": "/v1/tasks/job/result"}
            )
        clock[0] = 1000
        return httpx.Response(200, json={"status": "running"})

    parser = MinerUParser(settings_for(tmp_path), transport=httpx.MockTransport(handle))
    with pytest.raises(MinerUError, match="deadline"):
        parser.parse(source)
    assert sum(r.method == "POST" for r in calls) == 1


def test_response_size_is_bounded(tmp_path):
    source = tmp_path / "scan.pdf"
    source.write_bytes(b"fixture")
    settings = settings_for(tmp_path, mineru_max_response_bytes=1024)
    parser = MinerUParser(
        settings, transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"x" * 2048))
    )
    with pytest.raises(MinerUError, match="size limit"):
        parser.parse(source)


def test_credentials_file_supports_dotenv_without_echoing_invalid_key(tmp_path):
    secret = tmp_path / "key.env"
    secret.write_text("MINERU_API_KEY=" + KEY + "\n")
    settings = Settings(_env_file=None, mineru_api_key_file=secret)
    assert MinerUParser(settings).key == KEY
    secret.write_text("DO_NOT_ECHO_SECRET")
    with pytest.raises(MinerUError) as error:
        MinerUParser(settings)
    assert "DO_NOT_ECHO_SECRET" not in str(error.value)
