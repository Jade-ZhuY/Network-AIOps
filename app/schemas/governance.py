"""Only human workflow fields are client writable; verification uses saved evidence."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.security.redaction import redact_sensitive_text

CaseStatus = Literal["open", "in_progress", "resolved", "dismissed"]
CaseKind = Literal[
    "sql_review", "source_missing", "semantic_gap", "semantic_ambiguity", "execution_failure"
]


class CaseUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)
    status: Literal["open", "in_progress", "dismissed"]
    assignee: str = Field(default="", max_length=80)
    note: str = Field(min_length=5, max_length=1200)

    @field_validator("assignee", "note")
    @classmethod
    def clean(cls, value):
        return redact_sensitive_text(value.strip())

    @field_validator("note")
    @classmethod
    def meaningful(cls, value):
        if len(value) < 5:
            raise ValueError("A processing note is required")
        return value


class CaseVerify(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)
    proof_request_id: str = Field(min_length=1, max_length=64)
    resolution_kind: Literal["published_metric", "original_query_fixed", "clarification_confirmed"]
    metric_id: str | None = Field(default=None, max_length=64)
    note: str = Field(min_length=10, max_length=1200)
    confirm_scope: Literal[True]

    @model_validator(mode="after")
    def coherent_metric(self):
        if (self.resolution_kind == "published_metric") != bool(self.metric_id):
            raise ValueError("Only published-metric verification requires a metric ID")
        return self

    @field_validator("note")
    @classmethod
    def clean_note(cls, value):
        value = redact_sensitive_text(value.strip())
        if len(value) < 10:
            raise ValueError("Describe what was fixed and verified")
        return value

    @field_validator("confirm_scope", mode="before")
    @classmethod
    def explicit_confirmation(cls, value):
        if value is not True:
            raise ValueError("Explicit confirmation is required")
        return value
