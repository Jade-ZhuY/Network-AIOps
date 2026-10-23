import pytest
from pydantic import ValidationError

from app.config import ROOT, Settings


@pytest.mark.parametrize("value", [None, "", "  ", "low", "high", "max"])
def test_optional_reasoning_effort(value):
    settings = Settings(_env_file=None, llm_reasoning_effort=value)
    assert settings.llm_reasoning_effort == (value if value in {"low", "high", "max"} else None)


def test_invalid_reasoning_effort_rejected():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, llm_reasoning_effort="invalid")


@pytest.mark.parametrize("value", [0, -1])
def test_embedding_batch_size_must_be_positive(value):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, embedding_batch_size=value)


def test_example_configuration_starts_offline(monkeypatch):
    for field in Settings.model_fields:
        monkeypatch.delenv(field.upper(), raising=False)
    settings = Settings(_env_file=ROOT / ".env.example")
    assert settings.llm_mode == "mock"
    assert settings.data_backend == "mock"
    assert settings.embedding_mode == "mock"
    assert settings.persistence_backend == "none"
    assert settings.llm_reasoning_effort is None
    assert settings.rag_vector_backend == "memory"


def test_sdk_import_preserves_explicit_settings_isolation(monkeypatch):
    for field in Settings.model_fields:
        monkeypatch.delenv(field.upper(), raising=False)
    import pymilvus  # noqa: F401

    settings = Settings(_env_file=None)
    assert settings.llm_mode == "mock"
    assert settings.embedding_mode == "mock"
    assert settings.rag_vector_backend == "memory"
