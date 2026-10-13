import pytest
from pypdf import PdfReader

from deploy.mineru.make_fixture import create
from deploy.mineru.probe import read_key, same_origin_url


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
