import pytest
from pydantic import ValidationError

from app.config import Settings
from app.security.redaction import redact_sensitive_text


@pytest.mark.parametrize(
    "text",
    [
        "sk_tr_ABCDEFGHIJKLMN123456",
        "Bearer aaaaaaaaaaaaaa123456",
        "mysql+pymysql://user:very-private@localhost/db",
        "password=private-value",
        "API_KEY=private-value",
    ],
)
def test_credentials_redacted(text):
    result = redact_sensitive_text(text)
    assert "REDACTED" in result
    assert "private-value" not in result
    assert "very-private" not in result


def test_config_errors_do_not_include_credentials():
    with pytest.raises(ValidationError) as error:
        Settings(_env_file=None, llm_mode="openai", llm_api_key="sk_private_secret_12345")
    assert "sk_private_secret_12345" not in str(error.value)


async def test_checkpoint_and_request_message_redacted(service):
    result = await service.analyze("BGP 原理，附带 API_KEY=private-value")
    assert "private-value" not in str(result)


def test_session_title_redacted():
    from app.schemas.models import SessionCreate

    assert "private-value" not in SessionCreate(title="调查 token=private-value").title
