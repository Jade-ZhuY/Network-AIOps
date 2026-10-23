"""Validated catalog shared by discovery, execution and evidence rendering."""

import hashlib
import json
import re
from pathlib import Path
from types import MappingProxyType
from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.semantics.capabilities import capabilities_document
from app.semantics.models import Metric, MetricOptions, MetricSemantics
from app.storage.models import VIEW_COLUMNS

# This release compiles nine reviewed metrics, not arbitrary SQL from a config file.
COMPILER_BINDINGS = {
    "packet_loss_pct": ("sample", "v_interface_metrics", "sample_time"),
    "latency_ms": ("sample", "v_interface_metrics", "sample_time"),
    "utilization_pct": ("sample", "v_interface_metrics", "sample_time"),
    "alarm_count": ("event_count", "v_alarm_events", "occurred_at"),
    "alarm_events": ("events", "v_alarm_events", "occurred_at"),
    "incident_summaries": ("incidents", "v_incident_summaries", "started_at"),
    "device_status": ("snapshot", "v_device_status", None),
    "interface_status": ("snapshot", "v_interface_status", None),
    "link_status": ("snapshot", "v_link_status", None),
}


class MetricDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: Metric
    label: str
    kind: Literal["sample", "event_count", "events", "incidents", "snapshot"]
    aliases: tuple[str, ...]
    view: str
    value_column: str | None = None
    unit: str | None
    description: str
    row_grain: tuple[str, ...]
    time_column: str | None
    time_policy: str
    default_grouping: tuple[str, ...]
    filters: tuple[str, ...]
    null_policy: str
    empty_policy: str
    unit_interpretation: str
    limitations: tuple[str, ...]

    @model_validator(mode="after")
    def valid_identifiers(self):
        if (self.kind, self.view, self.time_column) != COMPILER_BINDINGS[self.id]:
            raise ValueError("Metric definition disagrees with the reviewed compiler binding")
        columns = VIEW_COLUMNS.get(self.view)
        if columns is None:
            raise ValueError("Metric must reference an authorized view")
        names = (*self.row_grain, *self.default_grouping, *self.filters)
        names += tuple(n for n in (self.value_column, self.time_column) if n)
        if any(n not in columns for n in names):
            raise ValueError("Metric references an unknown or non-public column")
        if (self.kind == "snapshot") != (self.time_column is None):
            raise ValueError("Snapshots have no timestamp; other metrics require one")
        if self.kind == "sample" and not self.value_column:
            raise ValueError("Sample metrics require a value column")
        if self.kind == "sample" and (
            self.value_column != self.id or self.default_grouping != ("hostname", "interface_name")
        ):
            raise ValueError("Sample expression/grain disagrees with the reviewed compiler")
        if not self.aliases or any(not alias.strip() for alias in self.aliases):
            raise ValueError("Metric aliases must be nonempty")
        return self

    def matches(self, question: str) -> bool:
        return any(
            re.search(r"(?<![a-z0-9_])" + re.escape(alias) + r"(?![a-z0-9_])", question, re.I)
            if alias.isascii()
            else alias in question
            for alias in self.aliases
        )


class CatalogDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    metrics: tuple[MetricDefinition, ...]

    @model_validator(mode="after")
    def complete_catalog(self):
        if {metric.id for metric in self.metrics} != set(get_args(Metric)):
            raise ValueError("Catalog must define exactly the supported metrics")
        if len({metric.id for metric in self.metrics}) != len(self.metrics):
            raise ValueError("Duplicate metric identifier")
        aliases = [a.casefold() for metric in self.metrics for a in metric.aliases]
        if len(aliases) != len(set(aliases)):
            raise ValueError("Duplicate metric alias")
        return self


def load_catalog(path: Path) -> CatalogDocument:
    return CatalogDocument.model_validate_json(path.read_text(encoding="utf-8"))


DOCUMENT = load_catalog(Path(__file__).resolve().parents[2] / "data" / "metric_catalog.json")
DEFINITIONS = MappingProxyType({metric.id: metric for metric in DOCUMENT.metrics})
CATALOG_VERSION = DOCUMENT.version


def definition_hash(metric: Metric) -> str:
    payload = json.dumps(
        DEFINITIONS[metric].model_dump(mode="json"), sort_keys=True, ensure_ascii=False
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def public_catalog() -> dict:
    return {
        "version": CATALOG_VERSION,
        "capabilities": capabilities_document(),
        "metrics": {
            metric: {
                **definition.model_dump(mode="json"),
                "definition_hash": definition_hash(metric),
                "default_options": {"aggregation": "sample_mean", "grouping": "device_interface"}
                if definition.kind == "sample"
                else None,
                "supported_options": [
                    {"aggregation": "sample_mean", "grouping": "device_interface"},
                    {"aggregation": "sample_mean", "grouping": "device"},
                    {"aggregation": "interface_mean", "grouping": "device"},
                ]
                if definition.kind == "sample"
                else [],
            }
            for metric, definition in DEFINITIONS.items()
        },
    }


def resolved_semantics(metric: Metric, options: MetricOptions | None, plan) -> MetricSemantics:
    definition = DEFINITIONS[metric]
    selected = options or MetricOptions()
    grouping = list(definition.default_grouping)
    aggregation = {"event_count": "count_events", "snapshot": "last_known_snapshot"}.get(
        definition.kind, "event_details"
    )
    formula = "source rows (no aggregation)"
    execution = "sql"
    if definition.kind == "sample":
        aggregation = selected.aggregation
        grouping = ["hostname"] if selected.grouping == "device" else ["hostname", "interface_name"]
        formula = f"AVG({definition.value_column}) = SUM(non_null_values) / COUNT(non_null_values)"
        if selected.aggregation == "interface_mean":
            formula = f"MEAN(per_interface_AVG({definition.value_column})) over interfaces with non-null samples"
            execution = "interface_rollup"
    elif definition.kind == "event_count":
        formula = "COUNT(*) per hostname; no deduplication by alarm_type"
    filters = {"hostname": list(plan.devices)} if plan.devices else {}
    for field, value in (
        ("interface_name", plan.interface),
        ("severity", plan.severity),
        ("alarm_type", plan.alarm_type),
    ):
        if value and field in definition.filters:
            filters[field] = value
    return MetricSemantics(
        catalog_version=CATALOG_VERSION,
        definition_hash=definition_hash(metric),
        label=definition.label,
        aggregation=aggregation,
        grouping=grouping,
        formula=formula,
        time_column=definition.time_column,
        time_policy=definition.time_policy,
        null_policy=definition.null_policy,
        empty_policy=definition.empty_policy,
        unit_interpretation=definition.unit_interpretation,
        selection_source="explicit" if options else "default",
        applied_filters=filters,
        limitations=list(definition.limitations),
        execution=execution,
    )
