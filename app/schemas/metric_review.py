"""Human review and immutable, named metric contracts (not an SQL example cache)."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.generated_sql import SqlRequestContext
from app.security.redaction import redact_sensitive_text


class QueryReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    verdict: Literal["approved", "changes_requested"]
    comment: str = Field(default="", max_length=1200)
    expected_revision: int = Field(ge=0)

    @field_validator("comment")
    @classmethod
    def clean_comment(cls, value):
        return redact_sensitive_text(value.strip())


class PublishMetricInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str = Field(min_length=2, max_length=80)
    aliases: list[str] = Field(default_factory=list, max_length=8)
    description: str = Field(min_length=10, max_length=1200)
    review_revision: int = Field(ge=1)
    confirm_contract: Literal[True]

    @field_validator("label", "description")
    @classmethod
    def nonblank(cls, value):
        value = redact_sensitive_text(value.strip())
        if not value:
            raise ValueError("Text must not be blank")
        return value

    @field_validator("description")
    @classmethod
    def meaningful_description(cls, value):
        if len(value) < 10:
            raise ValueError("Description needs at least 10 non-padding characters")
        return value

    @field_validator("aliases")
    @classmethod
    def aliases_clean(cls, values):
        if any(not value.strip() or len(value.strip()) > 80 for value in values):
            raise ValueError("Aliases must contain 1–80 characters")
        return list(dict.fromkeys(redact_sensitive_text(v.strip()) for v in values))

    @field_validator("label")
    @classmethod
    def name_syntax(cls, value):
        if len(value) < 2 or any(c in value for c in '\n\r「」“”"'):
            raise ValueError("Metric name cannot contain quotes or newlines")
        return value

    @field_validator("confirm_contract", mode="before")
    @classmethod
    def explicit_confirmation(cls, value):
        if value is not True:
            raise ValueError("Explicit boolean confirmation is required")
        return value


class ReviewedMetricPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    metric_id: str
    version: int
    definition_hash: str
    label: str
    request_context: SqlRequestContext


class ReviewedMetricEvidence(BaseModel):
    query_id: str
    executed_at_utc: str | None = None
    kind: Literal["reviewed_metric"] = "reviewed_metric"
    metric_id: str
    metric_version: int
    definition_hash: str
    label: str
    sql: str
    parameters: dict
    columns: list[str]
    output_units: dict[str, str]
    rows: list[dict]
    row_count: int
    truncated: bool
    source_views: list[str]
    data_source: str
    description: str
    request_context: SqlRequestContext
    verification_status: Literal["human_reviewed"] = "human_reviewed"
    reviewed_by: str
    reviewed_at: str
    contract: dict


class ReviewedMetricResult(BaseModel):
    status: Literal["ok", "no_data", "forbidden", "timeout", "error", "clarify"]
    queries: list[ReviewedMetricEvidence] = Field(default_factory=list)
    request_context: SqlRequestContext | None = None
    warnings: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
