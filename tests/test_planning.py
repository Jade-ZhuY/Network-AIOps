from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.agents.planning import build_route_plan, resolve_window
from app.schemas.models import QueryPlan, RoutePlan

NOW = datetime(2026, 10, 11, 9, tzinfo=UTC)


@pytest.mark.parametrize(
    ("question", "route"),
    [
        ("OSPF 为什么使用 LSDB？与 RIP 区别是什么？", "rag"),
        ("BGP 邻居 Down 的排查方法是什么？", "rag"),
        ("解释 BGP 协议原理", "rag"),
        ("查询 R2 昨天严重告警", "sql"),
        ("查询 R2 最近 24 小时 eth1 平均丢包率", "sql"),
        ("R2 昨天下午 BGP 断连原因分析", "both"),
        ("分析 R3 昨天 OSPF 邻居故障", "both"),
        ("R4 昨天 RTT 和利用率高，为什么？", "both"),
        ("Explain how OSPF works", "rag"),
        ("Query R2 alarms yesterday", "sql"),
        ("Why did R2 BGP fail yesterday?", "both"),
    ],
)
def test_routes(question, route):
    plan = build_route_plan(question, NOW, "Asia/Shanghai")
    assert plan.route == route
    assert not plan.needs_clarification


def test_relative_time_and_afternoon():
    start, end = resolve_window("昨天下午", NOW, "Asia/Shanghai")
    assert start == datetime(2026, 10, 10, 4, tzinfo=UTC)
    assert end == datetime(2026, 10, 10, 10, tzinfo=UTC)
    start, end = resolve_window("最近 24 小时", NOW, "Asia/Shanghai")
    assert (end - start).total_seconds() == 86400


def test_timezone_changes_day_boundary():
    shanghai, _ = resolve_window("昨天", NOW, "Asia/Shanghai")
    utc, _ = resolve_window("昨天", NOW, "UTC")
    assert shanghai != utc


@pytest.mark.parametrize(
    "question",
    ["查询昨天告警", "查询 R2 丢包率", "查询 R2 2026-99-99 告警", "查询 R2 最近 99999 小时告警"],
)
def test_clarification(question):
    plan = build_route_plan(question, NOW, "Asia/Shanghai")
    assert plan.needs_clarification
    assert plan.clarification_question


def test_followup_entities_and_time():
    first = "查询昨天 R2 的严重告警"
    followup = build_route_plan("那同一时间 R3 呢？", NOW, "Asia/Shanghai", [first])
    assert followup.query_plan.devices == ["R3"]
    assert followup.query_plan.severity == "critical"
    assert (
        followup.query_plan.start_utc
        == build_route_plan(first, NOW, "Asia/Shanghai").query_plan.start_utc
    )
    comparison = build_route_plan(
        "两台设备哪个更异常？比较一下", NOW, "Asia/Shanghai", [first, "查询昨天 R3 的严重告警"]
    )
    assert comparison.query_plan.devices == ["R2", "R3"]
    assert comparison.route == "both"


def test_new_knowledge_does_not_inherit_sql_context():
    plan = build_route_plan("OSPF 协议原理是什么？", NOW, "Asia/Shanghai", ["查询昨天 R2 告警"])
    assert plan.route == "rag"
    assert plan.query_plan is None


def test_query_contract():
    with pytest.raises(ValidationError):
        QueryPlan(start_utc=datetime(2026, 10, 10), end_utc=NOW)
    with pytest.raises(ValidationError):
        QueryPlan(start_utc=NOW, end_utc=NOW)
    with pytest.raises(ValidationError):
        QueryPlan(metrics=["root_cause"])
    with pytest.raises(ValidationError):
        RoutePlan(route="both", normalized_question="x")
