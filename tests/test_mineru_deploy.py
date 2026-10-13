from pathlib import Path

import pytest
from pypdf import PdfReader

from deploy.mineru.make_fixture import create
from deploy.mineru.probe import read_key, same_origin_url
from deploy.mineru.webui_start import launch_configuration


@pytest.mark.parametrize(
    "value",
    [
        "http://other-host:8000/v1/tasks/a",
        "https://example.com:8000/v1/tasks/a",
        "http://user:pass@example.com/v1/tasks/a",
    ],
)
def test_task_urls_never_forward_bearer_to_another_origin(value):
    with pytest.raises(ValueError):
        same_origin_url("http://example.com:8000", value)


def test_relative_and_default_port_urls():
    assert (
        same_origin_url("http://example.com:8000", "/v1/tasks/a")
        == "http://example.com:8000/v1/tasks/a"
    )
    assert (
        same_origin_url("https://example.com", "https://example.com:443/v1/tasks/a")
        == "https://example.com:443/v1/tasks/a"
    )


def test_smoke_fixture_contains_only_synthetic_two_page_data(tmp_path):
    path = tmp_path / "smoke.pdf"
    create(path)
    pages = PdfReader(path).pages
    assert len(pages) == 2
    assert "BGP" in pages[0].extract_text()
    assert "synthetic deployment fixtures" in pages[0].extract_text()
    assert "6.06" in pages[1].extract_text() and "R3" in pages[1].extract_text()


def test_key_reader_supports_secret_and_env_files_without_header_leaks(tmp_path):
    key = "MOCK_TOKEN_FOR_DEPLOYMENT_TEST_1234567890"
    path = tmp_path / "key"
    path.write_text(key + "\n")
    assert read_key(path) == key
    path.write_text("MINERU_API_URL=http://HOST:PORT\nMINERU_API_KEY=" + key + "\n")
    assert read_key(path) == key
    path.write_text("MINERU_API_URL=http://HOST:PORT\nPRIVATE_VALUE_DO_NOT_ECHO\n")
    with pytest.raises(ValueError, match="Invalid MinerU key file format") as error:
        read_key(path)
    assert "PRIVATE_VALUE_DO_NOT_ECHO" not in str(error.value)


def test_webui_uses_writable_artifacts_and_existing_api_without_key_in_argv(tmp_path):
    key = "MOCK_WEBUI_KEY_123456789012345678901234"
    path = tmp_path / "key"
    path.write_text(key)
    original = {"MINERU_API_KEY_FILE": str(path), "PATH": "/usr/local/bin"}
    command, environment = launch_configuration(original)
    assert key not in " ".join(command)
    assert "--api-key" not in command
    assert command[command.index("--api-url") + 1] == "http://api:8000"
    assert command[command.index("--output-dir") + 1] == "/data/output"
    assert command[command.index("--server-name") + 1] == "0.0.0.0"
    assert environment["MINERU_API_KEY"] == key
    assert environment["PATH"] == "/usr/local/bin"
    assert "MINERU_API_KEY" not in original


def test_webui_rejects_other_api_origins(tmp_path):
    path = tmp_path / "key"
    path.write_text("MOCK_WEBUI_KEY_123456789012345678901234")
    with pytest.raises(ValueError, match="existing API"):
        launch_configuration(
            {"MINERU_API_KEY_FILE": str(path), "MINERU_API_URL": "http://other-host:8000"}
        )


@pytest.mark.parametrize("key", ["short", "PRIVATE_VALUE_DO_NOT_ECHO\n" * 2])
def test_webui_invalid_key_errors_do_not_echo_contents(tmp_path, key):
    path = tmp_path / "key"
    path.write_text(key)
    with pytest.raises(ValueError, match="Invalid MinerU API key file") as error:
        launch_configuration({"MINERU_API_KEY_FILE": str(path)})
    assert "PRIVATE_VALUE_DO_NOT_ECHO" not in str(error.value)


def test_requested_public_webui_mapping_does_not_publish_the_backend_api():
    compose = (Path(__file__).resolve().parents[1] / "deploy/mineru/compose.yaml").read_text()
    api, webui = compose.split("  webui:\n", 1)
    assert '"127.0.0.1:18000:8000"' in api
    assert '"0.0.0.0:18000:8000"' not in api
    assert '"0.0.0.0:7860:7860"' in webui
    assert "read_only: true" in webui
