"""Third-layer SQL drafts and evidence, separate from verified metric evidence."""

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class GeneratedSqlDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    disposition: Literal["query", "clarify", "unavailable"]
    sql: str = Field(default="", max_length=12000)
    parameters: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
    devices: list[str] = Field(default_factory=list, max_length=10)
    interface: str | None = Field(default=None, max_length=64)
    all_devices: bool = False
    use_context: bool = False
    time_expression: str | None = Field(default=None, max_length=160)
    severity: Literal["critical", "major", "minor", "warning"] | None = None
    alarm_type: Literal["BGP_NEIGHBOR_DOWN", "OSPF_ADJACENCY_DOWN", "HIGH_UTILIZATION"] | None = (
        None
    )
    description: str = Field(default="", max_length=600)
    assumptions: list[str] = Field(default_factory=list, max_length=8)
    reason: str = Field(default="", max_length=600)


class SqlRequestContext(BaseModel):
    """Server-validated request scope, distinct from authorization Scope."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    devices: list[str] = Field(default_factory=list, max_length=10)
    all_devices: bool = False
    interface: str | None = None
    start_utc: datetime | None = None
    end_utc: datetime | None = None
    timezone: str = "Asia/Shanghai"
    severity: str | None = None
    alarm_type: str | None = None
    time_basis: Literal["request", "context", "none"] = "none"
    ignored_model_time_expression: bool = False

    @field_validator("start_utc", "end_utc")
    @classmethod
    def aware_utc(cls, value):
        if value is not None and value.tzinfo is None:
            raise ValueError("Request timestamps must be timezone aware")
        return value.astimezone(UTC) if value is not None else None

    @model_validator(mode="after")
    def valid_window(self):
        if bool(self.start_utc) != bool(self.end_utc):
            raise ValueError("Both time boundaries are required")
        if self.start_utc and self.end_utc <= self.start_utc:
            raise ValueError("Time boundaries must be ordered")
        return self


class GeneratedSqlEvidence(BaseModel):
    query_id: str
    executed_at_utc: str | None = None
    kind: Literal["generated_sql"] = "generated_sql"
    origin: Literal["model_sql"] = "model_sql"
    sql: str
    parameters: dict[str, Any]
    columns: list[str]
    output_units: dict[str, str] = Field(default_factory=dict)
    rows: list[dict[str, Any]]
    row_count: int
    truncated: bool = False
    business_limit: int | None = Field(default=None, ge=1)
    row_budget: int | None = Field(default=None, ge=1)
    source_views: list[str]
    data_source: str
    description: str = "模型生成的受限只读 SQL 查询；业务口径待人工核对"
    verification_status: Literal["unverified"] = "unverified"
    catalog_version: str
    assumptions: list[str] = Field(default_factory=list)
    request_context: SqlRequestContext
    structural_checks: list[str] = Field(default_factory=list)


class GeneratedSqlResult(BaseModel):
    status: Literal["ok", "no_data", "clarify", "unavailable", "forbidden", "timeout", "error"]
    queries: list[GeneratedSqlEvidence] = Field(default_factory=list)
    planner: Literal["llm", "mock"] = "llm"
    verification_status: Literal["unverified"] = "unverified"
    cache_used: Literal[False] = False
    warnings: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    reason_codes: list[str] = Field(default_factory=list)
    clarification_question: str | None = None
    repair_attempts: int = 0
    request_context: SqlRequestContext | None = None
    question: str = ""
    generation_attempted: bool = False
