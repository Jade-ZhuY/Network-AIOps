from datetime import UTC, datetime
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.security.redaction import redact_sensitive_text

Route = Literal["rag", "sql", "both"]
Metric = Literal[
    "alarm_count",
    "alarm_events",
    "packet_loss_pct",
    "latency_ms",
    "utilization_pct",
    "device_status",
    "interface_status",
    "link_status",
    "incident_summaries",
]
ToolStatus = Literal["ok", "no_data", "no_evidence", "forbidden", "timeout", "error"]


class Scope(BaseModel):
    """Server-owned scope. Never part of the public request schema."""

    model_config = ConfigDict(frozen=True)
    tenant_id: str = "demo-tenant"
    device_ids: tuple[int, ...] = (1, 2, 3, 4)
    knowledge_groups: tuple[str, ...] = ("netops",)


class QueryPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    devices: list[str] = Field(default_factory=list, max_length=10)
    interface: str | None = Field(default=None, max_length=64)
    start_utc: datetime | None = None
    end_utc: datetime | None = None
    metrics: list[Metric] = Field(default_factory=lambda: ["alarm_events"])
    severity: Literal["critical", "major", "minor", "warning"] | None = None
    alarm_type: Literal["BGP_NEIGHBOR_DOWN", "OSPF_ADJACENCY_DOWN", "HIGH_UTILIZATION"] | None = (
        None
    )

    @field_validator("start_utc", "end_utc")
    @classmethod
    def utc_time(cls, value: datetime | None):
        if value is not None and value.tzinfo is None:
            raise ValueError("Query time must be timezone-aware")
        return value.astimezone(UTC) if value else None

    @model_validator(mode="after")
    def valid_window(self):
        if bool(self.start_utc) != bool(self.end_utc):
            raise ValueError("Both time boundaries are required")
        if self.start_utc and self.end_utc <= self.start_utc:
            raise ValueError("End time must follow start time")
        return self


class RoutePlan(BaseModel):
    route: Route
    normalized_question: str
    rag_task: str | None = None
    sql_task: str | None = None
    query_plan: QueryPlan | None = None
    needs_clarification: bool = False
    clarification_question: str | None = None

    @model_validator(mode="after")
    def coherent_tasks(self):
        if self.needs_clarification and not self.clarification_question:
            raise ValueError("Clarification requires a question")
        if not self.needs_clarification:
            if self.route in ("rag", "both") and not self.rag_task:
                raise ValueError("RAG task missing")
            if self.route in ("sql", "both") and (not self.sql_task or not self.query_plan):
                raise ValueError("SQL task/plan missing")
        return self


class Citation(BaseModel):
    doc_id: str
    chunk_id: str
    title: str
    section: str | None = None
    page: int | None = None
    source: str
    document_version: str
    updated_at: str
    text: str
    score: float


class RagResult(BaseModel):
    status: ToolStatus
    summary: str = ""
    citations: list[Citation] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    data_source: str = "demo-documents:in-memory-hybrid"


class QueryEvidence(BaseModel):
    query_id: str
    metric: Metric
    sql: str
    parameters: dict[str, Any]
    columns: list[str]
    rows: list[dict[str, Any]]
    row_count: int
    truncated: bool = False
    unit: str | None = None
    description: str
    data_source: str
    data_freshness_utc: str | None = None


class SqlResult(BaseModel):
    status: ToolStatus
    queries: list[QueryEvidence] = Field(default_factory=list)
    time_range_utc: list[str] = Field(default_factory=list)
    timezone: str = "Asia/Shanghai"
    warnings: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)


class Claim(BaseModel):
    text: str
    evidence_refs: list[str] = Field(min_length=1)


class Hypothesis(Claim):
    strength: Literal["supported", "to_verify"] = "to_verify"


class NetworkReport(BaseModel):
    answer_type: Literal["knowledge", "data", "diagnosis"]
    status: Literal["completed", "partial", "no_evidence", "needs_clarification", "failed"]
    summary: str
    question: str
    timezone: str
    time_range_utc: list[str] = Field(default_factory=list)
    facts: list[Claim] = Field(default_factory=list)
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    next_checks: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    data_freshness: list[str] = Field(default_factory=list)
    data_mode: str = "demo"


class AnalyzeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=1, max_length=4000)
    timezone: str = "Asia/Shanghai"

    @field_validator("message")
    @classmethod
    def nonblank(cls, value: str):
        value = value.strip()
        if not value:
            raise ValueError("Message is empty")
        return value

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str):
        try:
            ZoneInfo(value)
        except (KeyError, ValueError) as exc:
            raise ValueError("Unknown IANA timezone") from exc
        return value


class ChatRequest(AnalyzeRequest):
    session_id: str = Field(min_length=1, max_length=64)


class SessionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(default="新调查", min_length=1, max_length=100)
    timezone: str = "Asia/Shanghai"

    @field_validator("title")
    @classmethod
    def title_text(cls, value):
        value = redact_sensitive_text(value.strip())
        if not value:
            raise ValueError("Title is empty")
        return value

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value):
        return AnalyzeRequest.valid_timezone(value)


class BusinessCompletion(BaseModel):
    completed: bool


class SupervisorDecision(BaseModel):
    route: Route
    needs_clarification: bool


class ReportDecision(BaseModel):
    """LLM selects evidence-backed conclusions; it never writes raw numeric facts."""

    hypothesis_order: list[int] = Field(default_factory=list, max_length=10)
