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


def test_example_configuration_starts_offline(monkeypatch):
    for field in Settings.model_fields:
        monkeypatch.delenv(field.upper(), raising=False)
    settings = Settings(_env_file=ROOT / ".env.example")
    assert settings.llm_mode == "mock"
    assert settings.data_backend == "mock"
    assert settings.embedding_mode == "mock"
    assert settings.persistence_backend == "none"
    assert settings.llm_reasoning_effort is None
