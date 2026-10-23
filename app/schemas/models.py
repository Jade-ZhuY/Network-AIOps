from datetime import UTC, datetime
from typing import Any, Literal
from zoneinfo import ZoneInfo

from langchain_core.documents import Document
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.metric_review import ReviewedMetricPlan
from app.security.redaction import redact_sensitive_text
from app.semantics.models import Metric, MetricMatch, MetricOptions, MetricSemantics, SemanticIssue

Route = Literal["rag", "sql", "both"]
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
    metric_options: dict[Metric, MetricOptions] = Field(default_factory=dict)
    metric_catalog_version: str | None = None
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
        if set(self.metric_options) - set(self.metrics):
            raise ValueError("Metric options must belong to selected metrics")
        return self


class RoutePlan(BaseModel):
    route: Route
    normalized_question: str
    rag_task: str | None = None
    sql_task: str | None = None
    query_plan: QueryPlan | None = None
    reviewed_metric_plan: ReviewedMetricPlan | None = None
    needs_clarification: bool = False
    clarification_question: str | None = None
    semantic_issues: list[SemanticIssue] = Field(default_factory=list)
    metric_match: MetricMatch | None = None

    @model_validator(mode="after")
    def coherent_tasks(self):
        if self.needs_clarification and not self.clarification_question:
            raise ValueError("Clarification requires a question")
        stopped = self.metric_match is not None and self.metric_match.status in ("miss", "error")
        if not self.needs_clarification and not stopped:
            if self.route in ("rag", "both") and not self.rag_task:
                raise ValueError("RAG task missing")
            if self.route in ("sql", "both") and (
                not self.sql_task or not (self.query_plan or self.reviewed_metric_plan)
            ):
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
    parent_id: str | None = None
    parent_text: str | None = None
    section_path: list[str] = Field(default_factory=list)
    matched_child_ids: list[str] = Field(default_factory=list)
    section_block_ids: list[str] = Field(default_factory=list)


class RagResult(BaseModel):
    status: ToolStatus
    summary: str = ""
    citations: list[Citation] = Field(default_factory=list)
    context_documents: list[Document] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    data_source: str = "demo-documents:in-memory-hybrid"


class QueryEvidence(BaseModel):
    query_id: str
    executed_at_utc: str | None = None
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
    semantics: MetricSemantics | None = None
    source_rows: list[dict[str, Any]] | None = None


class SqlResult(BaseModel):
    status: ToolStatus
    queries: list[QueryEvidence] = Field(default_factory=list)
    time_range_utc: list[str] = Field(default_factory=list)
    timezone: str = "Asia/Shanghai"
    warnings: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    semantic_issues: list[SemanticIssue] = Field(default_factory=list)


class Claim(BaseModel):
    text: str
    evidence_refs: list[str] = Field(min_length=1)


class Hypothesis(Claim):
    strength: Literal["supported", "to_verify"] = "to_verify"


class SourceQuote(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_id: str = Field(min_length=1, max_length=32)
    quote: str = Field(min_length=1, max_length=800)


class RagParagraph(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=2500)
    evidence: list[SourceQuote] = Field(min_length=1, max_length=4)


class RagAnswerDraft(BaseModel):
    """Model-authored answer; source metadata is resolved only by the backend."""

    model_config = ConfigDict(extra="forbid")
    status: Literal["answered", "partial", "insufficient_context"]
    paragraphs: list[RagParagraph] = Field(default_factory=list, max_length=8)
    missing_information: list[str] = Field(default_factory=list, max_length=8)


class RagAnswerReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approved: bool
    feedback: str = Field(default="", max_length=2000)


class ReportStep(BaseModel):
    action: Literal["generate", "search", "read_source", "validate", "review", "revise"]
    outcome: str
    source_id: str | None = None


class ReportCitation(BaseModel):
    source_id: str
    parent_id: str
    doc_id: str
    title: str
    source: str
    page: int | None = None
    section_path: list[str] = Field(default_factory=list)
    quote: str
    matched_child_ids: list[str] = Field(default_factory=list)


class NetworkReport(BaseModel):
    answer_type: Literal["knowledge", "data", "diagnosis"]
    status: Literal[
        "completed", "partial", "no_evidence", "needs_clarification", "not_matched", "failed"
    ]
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
    generation_mode: Literal[
        "evidence_template", "agentic_rag", "mock_rag", "model_sql", "reviewed_metric"
    ] = "evidence_template"
    verification_status: Literal["unverified", "human_reviewed"] | None = None
    requires_review: bool = False
    source_citations: list[ReportCitation] = Field(default_factory=list)
    generation_steps: list[ReportStep] = Field(default_factory=list)


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
