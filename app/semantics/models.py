from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

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
Aggregation = Literal["sample_mean", "interface_mean"]
Grouping = Literal["device_interface", "device"]


class MetricOptions(BaseModel):
    """No SQL expressions, identifiers, or weights are accepted from a caller/model."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    aggregation: Aggregation = "sample_mean"
    grouping: Grouping = "device_interface"


class SemanticIssue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    code: str
    message: str
    metric: Metric | None = None
    choices: list[str] = Field(default_factory=list)


class MetricMatch(BaseModel):
    """Capability matching, not a promise of available data or a model confidence score."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    status: Literal["hit", "clarify", "miss", "not_applicable", "error"]
    planner: Literal["rule_mock", "llm", "reviewed_catalog"] = "rule_mock"
    catalog_version: str
    matched_metrics: list[Metric] = Field(default_factory=list)
    matched_reviewed_metrics: list[str] = Field(default_factory=list)
    reason_codes: list[str] = Field(default_factory=list)
    unmatched_requests: list[str] = Field(default_factory=list)
    next_layer: Literal["historical_sql", "text_to_sql"] | None = None


class MetricIntentDecision(BaseModel):
    """LLM output contains metric intent only, never SQL, formulae or authorization."""

    model_config = ConfigDict(extra="forbid")
    route: Literal["rag", "sql", "both"]
    disposition: Literal["hit", "clarify", "miss"]
    metrics: list[Metric] = Field(default_factory=list, max_length=9)
    metric_mentions: dict[Metric, str] = Field(default_factory=dict)
    devices: list[str] = Field(default_factory=list, max_length=10)
    interface: str | None = Field(default=None, max_length=64)
    all_devices: bool = False
    use_context: bool = False
    time_expression: str | None = Field(default=None, max_length=160)
    metric_options: dict[Metric, MetricOptions] = Field(default_factory=dict)
    aggregation_mentions: dict[Metric, str] = Field(default_factory=dict)
    severity: Literal["critical", "major", "minor", "warning"] | None = None
    alarm_type: Literal["BGP_NEIGHBOR_DOWN", "OSPF_ADJACENCY_DOWN", "HIGH_UTILIZATION"] | None = (
        None
    )
    features: list[
        Literal[
            "window_summary",
            "event_details",
            "status_snapshot",
            "diagnosis",
            "device_comparison",
            "time_series",
            "ranking",
            "percentile",
            "threshold_filter",
            "period_comparison",
            "raw_samples",
            "custom_grouping",
            "weighted_mean",
            "historical_status",
            "other",
        ]
    ] = Field(default_factory=list, max_length=12)
    unmatched_requests: list[str] = Field(default_factory=list, max_length=10)
    clarification_question: str | None = Field(default=None, max_length=600)


class MetricSemantics(BaseModel):
    """Server-owned resolved contract, carried alongside every query's evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    catalog_version: str
    definition_hash: str
    label: str
    aggregation: str
    grouping: list[str]
    formula: str
    time_column: str | None
    time_policy: str
    null_policy: str
    empty_policy: str
    unit_interpretation: str
    selection_source: Literal["default", "explicit"]
    applied_filters: dict[str, object] = Field(default_factory=dict)
    limitations: list[str] = Field(default_factory=list)
    execution: Literal["sql", "interface_rollup"] = "sql"
