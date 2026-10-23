import json
from copy import deepcopy
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.agents.planning import build_route_plan
from app.config import ROOT, Settings
from app.main import create_app
from app.schemas.models import QueryPlan
from app.semantics.catalog import DEFINITIONS, CatalogDocument, public_catalog
from app.semantics.models import MetricOptions
from app.storage.fixtures import demo_records

NOW = datetime(2026, 10, 11, 9, tzinfo=UTC)


def query_plan(**kwargs):
    return QueryPlan(
        devices=["R2"],
        metrics=["packet_loss_pct"],
        start_utc=datetime(2026, 10, 10, tzinfo=UTC),
        end_utc=datetime(2026, 10, 11, tzinfo=UTC),
        **kwargs,
    )


def two_interfaces():
    records = demo_records()
    records["network_interfaces"].append(
        dict(
            interface_id=22,
            device_id=2,
            interface_name="eth2",
            admin_status="up",
            oper_status="up",
        )
    )
    records["network_metrics"].append(
        dict(
            metric_id=250,
            device_id=2,
            interface_id=22,
            sample_time=datetime(2026, 10, 10, 10, tzinfo=UTC),
            packet_loss_pct=90.0,
            latency_ms=9.0,
            utilization_pct=10.0,
        )
    )
    return records


def test_catalog_is_complete_versioned_and_public():
    catalog = public_catalog()
    assert catalog["version"] == "1.0.0"
    assert len(catalog["metrics"]) == 9
    for metric in catalog["metrics"].values():
        assert len(metric["definition_hash"]) == 64
        assert metric["row_grain"] and metric["time_policy"]
        assert metric["null_policy"] and metric["empty_policy"]
        assert metric["unit_interpretation"]
    assert "tenant_id" not in json.dumps(catalog)
    assert "root_cause" not in json.dumps(catalog)
    assert DEFINITIONS["packet_loss_pct"].matches("查询掉包")
    assert DEFINITIONS["latency_ms"].matches("平均 RTT")
    assert not DEFINITIONS["packet_loss_pct"].matches("lossless")


@pytest.mark.parametrize("change", ["column", "duplicate", "alias", "missing", "timestamp"])
def test_invalid_catalog_fails_closed(change):
    document = json.loads((ROOT / "data" / "metric_catalog.json").read_text(encoding="utf-8"))
    if change == "column":
        document["metrics"][0]["value_column"] = "packet_loss_pct); DROP TABLE x"
    elif change == "duplicate":
        document["metrics"].append(deepcopy(document["metrics"][0]))
    elif change == "alias":
        document["metrics"][1]["aliases"].append("丢包")
    elif change == "missing":
        document["metrics"].pop()
    else:
        document["metrics"][-1]["time_column"] = "link_id"
    with pytest.raises(ValidationError):
        CatalogDocument.model_validate(document)


@pytest.mark.parametrize(
    "options",
    [
        {"packet_loss_pct": {"aggregation": "traffic_weighted"}},
        {"packet_loss_pct": {"grouping": "tenant_id"}},
        {"packet_loss_pct": {"sql": "SELECT 1"}},
        {"latency_ms": {"aggregation": "sample_mean"}},
    ],
)
def test_model_options_are_closed_enums(options):
    with pytest.raises(ValidationError):
        query_plan(metric_options=options)


def test_default_contract_is_attached_to_real_evidence(service, scope):
    result = service.query_service.query(query_plan(), scope, "UTC")
    evidence = result.queries[0]
    assert result.status == "ok"
    assert evidence.rows[0]["average_value"] == pytest.approx(6.06)
    assert evidence.semantics.aggregation == "sample_mean"
    assert evidence.semantics.grouping == ["hostname", "interface_name"]
    assert evidence.semantics.selection_source == "default"
    assert evidence.semantics.applied_filters == {"hostname": ["R2"]}
    assert "8.0" in evidence.semantics.unit_interpretation
    assert evidence.source_rows is None
    assert service.query_service.schema()["metric_catalog_version"] == "1.0.0"


def test_three_grains_produce_different_correct_results(service, scope):
    service.backend.records_factory = two_interfaces
    per_interface = service.query_service.query(query_plan(), scope, "UTC")
    assert [row["average_value"] for row in per_interface.queries[0].rows] == pytest.approx(
        [6.06, 90.0]
    )
    pooled = service.query_service.query(
        query_plan(
            metric_options={
                "packet_loss_pct": MetricOptions(grouping="device"),
            }
        ),
        scope,
        "UTC",
    )
    pooled_row = pooled.queries[0].rows[0]
    assert pooled_row["average_value"] == pytest.approx((30.3 + 90) / 6)
    assert "interface_name" not in pooled_row
    interface_mean = service.query_service.query(
        query_plan(
            metric_options={
                "packet_loss_pct": MetricOptions(aggregation="interface_mean", grouping="device"),
            }
        ),
        scope,
        "UTC",
    )
    evidence = interface_mean.queries[0]
    assert evidence.rows[0]["average_value"] == pytest.approx((6.06 + 90) / 2)
    assert evidence.rows[0]["sample_count"] == 6
    assert evidence.rows[0]["interface_count"] == 2
    assert len(evidence.source_rows) == 2
    assert evidence.semantics.execution == "interface_rollup"
    assert "GROUP BY hostname, interface_name" in evidence.sql
    assert "interface_name" not in evidence.columns


def test_nulls_are_not_zero_and_do_not_advance_metric_freshness(service, scope):
    records = demo_records()
    latest = dict(records["network_metrics"][5])
    latest.update(
        metric_id=250, packet_loss_pct=None, sample_time=datetime(2026, 10, 10, 12, tzinfo=UTC)
    )
    records["network_metrics"].append(latest)
    service.backend.records_factory = lambda: records
    result = service.query_service.query(query_plan(), scope, "UTC")
    row = result.queries[0].rows[0]
    assert row["sample_count"] == 5
    assert row["average_value"] == pytest.approx(6.06)
    assert "12:00" not in result.queries[0].data_freshness_utc
    for row in records["network_metrics"]:
        row["packet_loss_pct"] = None
    result = service.query_service.query(query_plan(), scope, "UTC")
    assert result.status == "no_data"
    assert not result.queries[0].rows


@pytest.mark.parametrize("incomplete", ["truncated", "unassigned"])
def test_interface_rollup_never_averages_incomplete_inputs(service, scope, incomplete):
    records = two_interfaces()
    if incomplete == "truncated":
        service.settings.sql_max_rows = 1
    else:
        records["network_metrics"][-1]["interface_id"] = None
    service.backend.records_factory = lambda: records
    result = service.query_service.query(
        query_plan(
            metric_options={
                "packet_loss_pct": MetricOptions(aggregation="interface_mean", grouping="device"),
            }
        ),
        scope,
        "UTC",
    )
    assert result.status == "error"
    assert result.queries == []
    assert "未计算" in result.missing_evidence[0]


@pytest.mark.parametrize(
    ("question", "code"),
    [
        ("查询 R2 昨天设备整体平均丢包率", "ambiguous_aggregation"),
        ("查询 R2 昨天按流量加权平均丢包率", "unsupported_weighting"),
        ("查询 R2 昨天包级总体丢包率", "unsupported_weighting"),
        ("查询 R2 昨天流量", "ambiguous_traffic"),
        ("查询 R2 昨天单向时延", "different_latency_metric"),
        ("查询 R2 昨天 jitter", "different_latency_metric"),
        ("查询 R2 昨天丢包包数", "unsupported_weighting"),
        ("查询 R2 昨天入方向利用率", "undefined_utilization_direction"),
        ("查询 R2 昨天 P95 RTT", "unsupported_statistic"),
        ("查询 R2 昨天设备状态", "snapshot_not_history"),
        ("查询 R2 昨天未结束的故障记录", "incident_time_basis"),
        ("统计 R2 昨天去重后的告警数量", "ambiguous_alarm_count"),
        ("查询 R2 昨天 eth1 的告警数量", "unsupported_interface_filter"),
    ],
)
async def test_semantic_ambiguity_stops_before_business_tools(service, question, code):
    result = await service.analyze(question)
    if code == "different_latency_metric":
        assert result["status"] == "not_matched"
        assert result["metric_match"]["status"] == "miss"
        assert "unsupported_metric" in result["metric_match"]["reason_codes"]
        assert result["evidence"]["sql"] is None
        return
    if code in {
        "unsupported_weighting",
        "undefined_utilization_direction",
        "unsupported_statistic",
        "snapshot_not_history",
        "incident_time_basis",
    }:
        assert result["status"] == "not_matched"
        assert result["metric_match"]["status"] == "miss"
        assert code in result["metric_match"]["reason_codes"]
        assert result["evidence"]["sql"] is None
        return
    assert result["status"] == "needs_clarification"
    assert result["report_calls"] == 0
    assert not any(item["name"].startswith("tool.") for item in result["trace"])
    assert code in [issue["code"] for issue in result["clarification"]["semantic_issues"]]


def test_tool_layer_rechecks_semantics_without_planner(service, scope, monkeypatch):
    def unexpected(*args):
        pytest.fail("Semantic failures must not access the database")

    monkeypatch.setattr(service.backend, "read", unexpected)
    bad = query_plan(
        metric_options={"packet_loss_pct": MetricOptions(aggregation="interface_mean")}
    )
    assert service.query_service.query(bad, scope, "UTC").status == "error"
    wrong = query_plan()
    result = service.query_service.query(wrong, scope, "UTC", "设备级合并采样点等权")
    assert result.status == "error"
    assert result.semantic_issues[0].code == "selection_mismatch"
    assert service.query_service.query(wrong, scope, "UTC", "按包数加权丢包率").status == "error"
    stale = query_plan(metric_catalog_version="0.0.1")
    assert (
        service.query_service.query(stale, scope, "UTC").semantic_issues[0].code
        == "catalog_version_mismatch"
    )


@pytest.mark.mysql
def test_live_mysql_mean_profiles(mysql_service, scope):
    for option in (
        MetricOptions(),
        MetricOptions(grouping="device"),
        MetricOptions(aggregation="interface_mean", grouping="device"),
    ):
        result = mysql_service.query_service.query(
            query_plan(metric_options={"packet_loss_pct": option}), scope, "UTC"
        )
        assert result.status == "ok"
        assert result.queries[0].rows[0]["average_value"] == pytest.approx(6.06)
        assert result.queries[0].semantics.aggregation == option.aggregation
        assert result.queries[0].data_source == "mysql:authorized-views"


def test_options_are_scoped_to_the_named_metric():
    plan = build_route_plan("查询 R2 昨天丢包率按设备级合并采样点等权，时延按接口等权", NOW, "UTC")
    assert not plan.needs_clarification
    assert plan.query_plan.metric_options["packet_loss_pct"].aggregation == "sample_mean"
    assert plan.query_plan.metric_options["latency_ms"].aggregation == "interface_mean"


async def test_device_and_interface_rollup_reports_keep_the_selected_mean(service):
    service.backend.records_factory = two_interfaces
    for choice, expected in [
        ("设备级合并采样点等权", "20.050"),
        ("先算每个接口均值，再按接口等权", "48.030"),
    ]:
        result = await service.analyze("查询 R2 昨天的丢包率，" + choice)
        assert result["status"] == "completed"
        assert expected in result["report"]["summary"]
        assert "口径" in "".join(result["report"]["limitations"])


@pytest.mark.parametrize("method", ["先按接口算，再按设备平均", "先算每个接口均值，再按设备平均"])
def test_two_stage_mean_phrase_survives_clause_split(method):
    plan = build_route_plan("查询 R2 昨天丢包率，" + method, NOW, "UTC")
    assert not plan.needs_clarification
    assert plan.query_plan.metric_options["packet_loss_pct"].aggregation == "interface_mean"


@pytest.mark.parametrize("method", ["采样点等权还是接口等权", "采样点等权和接口等权"])
def test_conflicting_methods_never_pick_one_silently(method):
    plan = build_route_plan("查询 R2 昨天丢包率，" + method, NOW, "UTC")
    assert plan.needs_clarification
    assert "conflicting_aggregation" in [issue.code for issue in plan.semantic_issues]


def test_catalog_endpoint_is_authenticated_and_read_only(settings):
    settings = Settings(_env_file=None, api_auth_token="engineer-semantic-test")
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/v1/metrics").status_code == 401
        response = client.get(
            "/api/v1/metrics", headers={"Authorization": "Bearer engineer-semantic-test"}
        )
        assert response.status_code == 200
        assert response.json() == public_catalog()
        assert client.post("/api/v1/metrics", json={}).status_code == 405


def test_semantic_choices_survive_clarification_and_followup():
    settings = Settings(
        _env_file=None, persistence_backend="memory", api_auth_token="semantic-test"
    )
    headers = {"Authorization": "Bearer semantic-test"}
    with TestClient(create_app(settings)) as client:
        sid = client.post("/api/v1/sessions", json={}, headers=headers).json()["session_id"]

        def chat(question):
            return client.post(
                "/api/v1/chat", json={"session_id": sid, "message": question}, headers=headers
            ).json()

        first = chat("查询 R2 昨天设备整体平均丢包率")
        assert first["status"] == "needs_clarification"
        assert chat("昨天")["status"] == "needs_clarification"
        resolved = chat("先算每个接口均值，再按接口等权")
        assert resolved["status"] == "completed"
        assert (
            resolved["evidence"]["sql"]["queries"][0]["semantics"]["aggregation"]
            == "interface_mean"
        )
        followup = chat("那同一时间 R3 呢？")
        assert followup["status"] == "completed"
        assert (
            followup["evidence"]["sql"]["queries"][0]["semantics"]["aggregation"]
            == "interface_mean"
        )
        assert chat("查询 R2 昨天接口状态")["status"] == "not_matched"
        snapshot = chat("查询最后已知状态快照")
        assert snapshot["status"] == "completed"
        assert snapshot["evidence"]["sql"]["queries"][0]["metric"] == "interface_status"
