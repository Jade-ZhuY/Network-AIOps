import re


def redact_sensitive_text(text: str) -> str:
    text = re.sub(r"(?<![A-Za-z0-9])sk[-_][A-Za-z0-9_-]{12,}", "[REDACTED_KEY]", text)
    text = re.sub(r"(?i)\bBearer\s+[A-Za-z0-9._~-]{12,}", "Bearer [REDACTED]", text)
    text = re.sub(r"([A-Za-z][A-Za-z0-9+.-]*://[^\s:/]+:)[^\s@]+(@)", r"\1[REDACTED]\2", text)
    return re.sub(
        r"(?i)((?:api[_ -]?key|password|passwd|secret|token|密码)\s*[:=]\s*)[^\s;\"']+",
        r"\1[REDACTED]",
        text,
    )
