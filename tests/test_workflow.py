import asyncio
from copy import deepcopy

import pytest

from app.observability.tracing import RequestTrace
from app.schemas.models import RagResult, SqlResult
from scripts.demo import QUESTIONS


@pytest.mark.parametrize(
    ("question", "route"),
    [
        (QUESTIONS[0], "rag"),
        (QUESTIONS[1], "sql"),
        (QUESTIONS[2], "both"),
        (QUESTIONS[3], "both"),
        (QUESTIONS[4], "both"),
    ],
)
async def test_three_routes_report_once(service, question, route):
    result = await service.analyze(question)
    assert result["route"] == route
    assert result["status"] == "completed"
    assert result["report_calls"] == 1
    assert [span["name"] for span in result["trace"]].count("agent.report") == 1
    assert bool(result["evidence"]["rag"]) == (route in ("rag", "both"))
    assert bool(result["evidence"]["sql"]) == (route in ("sql", "both"))
    if route == "both":
        assert result["report"]["hypotheses"]
        assert all(item["strength"] == "to_verify" for item in result["report"]["hypotheses"])


async def test_real_langchain_tool_loops(service, scope):
    from app.agents.planning import build_route_plan

    plan = build_route_plan(QUESTIONS[1], service.settings.demo_now, "Asia/Shanghai")
    trace = RequestTrace("test")
    result = await service.runtime.sql(
        plan.sql_task, plan.query_plan, scope, "Asia/Shanghai", trace
    )
    assert result.status == "ok"
    assert [event["name"] for event in trace.events] == [
        "tool.get_schema",
        "tool.query_network_metrics",
    ]
    trace = RequestTrace("test-rag")
    result = await service.runtime.rag("BGP 邻居断连", scope, trace)
    assert result.status == "ok"
    assert [event["name"] for event in trace.events] == ["tool.search_network_knowledge"]


async def test_both_barrier_waits_for_slow_branch(service, monkeypatch):
    original = service.runtime.sql
    completed = []

    async def delayed(*args):
        await asyncio.sleep(0.05)
        result = await original(*args)
        completed.append("sql")
        return result

    original_report = service.runtime.report

    async def checked_report(payload):
        assert completed == ["sql"]
        assert payload["rag_result"] and payload["sql_result"]
        return await original_report(payload)

    monkeypatch.setattr(service.runtime, "sql", delayed)
    monkeypatch.setattr(service.runtime, "report", checked_report)
    result = await service.analyze(QUESTIONS[2])
    assert result["status"] == "completed"
    assert result["report_calls"] == 1


async def test_previous_task_results_reset(service, scope):
    initial = {
        "question": QUESTIONS[2],
        "timezone": "Asia/Shanghai",
        "scope": scope,
        "request_id": "1",
        "trace": RequestTrace("1"),
        "messages": [{"role": "user", "content": QUESTIONS[2]}],
    }
    from app.schemas.context import InvocationContext

    first = await service.graph.ainvoke(initial, context=InvocationContext(scope, initial["trace"]))
    assert first["rag_result"] and first["sql_result"]
    previous = deepcopy({key: value for key, value in first.items() if key not in ("trace",)})
    second = await service.graph.ainvoke(
        {
            **previous,
            "question": QUESTIONS[0],
            "trace": RequestTrace("2"),
            "messages": [{"role": "user", "content": QUESTIONS[0]}],
        },
        context=InvocationContext(scope, RequestTrace("2")),
    )
    assert second["sql_result"] is None
    assert second["report_calls"] == 1
    assert not any(ref.startswith("query_") for ref in second["final_report"]["evidence_refs"])


async def test_stateless_requests_and_manual_context(service):
    first = await service.analyze("查询昨天 R2 的严重告警")
    second = await service.analyze("那同一时间 R3 呢？")
    assert first["status"] == "completed"
    assert second["status"] == "needs_clarification"
    supplied = await service.analyze("那同一时间 R3 呢？", history=["查询昨天 R2 的严重告警"])
    assert supplied["route"] == "sql"
    assert supplied["report_calls"] == 1
    assert service.graph.checkpointer is None
    assert not supplied["persistence_enabled"]


@pytest.mark.parametrize("question", ["查询昨天告警", "查询 R2 丢包率"])
async def test_clarify_without_running_tools(service, question):
    result = await service.analyze(question)
    assert result["status"] == "needs_clarification"
    assert result["report_calls"] == 0
    assert not any(span["name"].startswith("tool.") for span in result["trace"])


async def test_empty_sql_not_fake_zero(service):
    result = await service.analyze("查询 R2 2030-01-01 的丢包率")
    assert result["status"] == "no_evidence"
    assert result["evidence"]["sql"]["status"] == "no_data"
    assert result["report"]["facts"] == []


@pytest.mark.parametrize("side", ["rag", "sql"])
async def test_partial_branch_failure(service, monkeypatch, side):
    async def timeout(*args):
        raise TimeoutError("TEST_SECRET must not be exposed")

    monkeypatch.setattr(service.runtime, side, timeout)
    result = await service.analyze(QUESTIONS[2])
    assert result["status"] == "partial"
    assert result["report_calls"] == 1
    assert result["evidence"][side]["status"] == "timeout"
    assert "TEST_SECRET" not in str(result)
    assert any(event.get("error_type") == "TimeoutError" for event in result["trace"])


async def test_both_sides_fail_once(service, monkeypatch):
    async def rag(*args):
        return RagResult(status="error", missing_evidence=["document service offline"])

    async def sql(*args):
        return SqlResult(status="timeout", missing_evidence=["database timeout"])

    monkeypatch.setattr(service.runtime, "rag", rag)
    monkeypatch.setattr(service.runtime, "sql", sql)
    result = await service.analyze(QUESTIONS[2])
    assert result["status"] == "failed"
    assert not result["report"]["facts"]
    assert result["report_calls"] == 1


async def test_supervisor_and_report_errors_explicit(service, monkeypatch):
    async def fail(*args):
        raise ValueError("secret provider details")

    monkeypatch.setattr(service.runtime, "report", fail)
    report_failure = await service.analyze(QUESTIONS[2])
    assert report_failure["status"] == "failed"
    assert report_failure["evidence"]["sql"]["queries"]
    assert "secret provider details" not in str(report_failure)
    monkeypatch.setattr(service.runtime, "supervisor", fail)
    supervisor_failure = await service.analyze(QUESTIONS[0])
    assert supervisor_failure["status"] == "failed"
    assert supervisor_failure["report_calls"] == 0


async def test_parallel_requests_do_not_share_state(service):
    a, b = await asyncio.gather(service.analyze(QUESTIONS[0]), service.analyze(QUESTIONS[1]))
    assert a["request_id"] != b["request_id"]
    assert a["trace_id"] != b["trace_id"]
    assert a["evidence"]["sql"] is None
    assert b["evidence"]["rag"] is None


async def test_readonly_mutation_and_cross_tenant_denied(service):
    for question in ("删除所有告警数据", "查询 R99 昨天告警", "查询 R2 昨天系统账号密码"):
        result = await service.analyze(question)
        assert result["status"] == "failed"
        assert result["evidence"]["sql"]["status"] == "forbidden"
        assert not result["report"]["facts"]


def test_tool_budget_and_trace_snapshot():
    from app.agents.runtime import ToolBudget

    budget = ToolBudget()
    budget.consume("get_schema")
    budget.consume("query_network_metrics")
    with pytest.raises(ValueError, match="budget"):
        budget.consume("query_network_metrics")
    trace = RequestTrace("id")
    with trace.span("first"):
        pass
    snapshot = trace.snapshot()
    with trace.span("second"):
        pass
    assert len(snapshot) == 1
    assert len(trace.snapshot()) == 2
