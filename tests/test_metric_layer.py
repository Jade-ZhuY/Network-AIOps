import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field, ValidationError

from app.agents.metric_planning import compile_metric_intent, planner_catalog
from app.agents.mock_model import MockNetworkModel
from app.agents.planning import build_route_plan, resolve_window
from app.config import Settings
from app.main import create_app
from app.semantics.models import MetricIntentDecision

NOW = datetime(2026, 10, 11, 9, tzinfo=UTC)


def loss_intent(**updates):
    return MetricIntentDecision.model_validate(
        {
            "route": "sql",
            "disposition": "hit",
            "metrics": ["packet_loss_pct"],
            "metric_mentions": {"packet_loss_pct": "丢包率"},
            "devices": ["R2"],
            **updates,
        }
    )


class ScriptedIntentModel(MockNetworkModel):
    """Explicit scripted LLM substitute, exercising actual LangChain structured tools."""

    decisions: dict = Field(default_factory=dict)

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        payload = json.loads(next(m.content for m in messages if isinstance(m, HumanMessage)))
        if self.role == "supervisor" and payload.get("phase") == "metric_plan":
            name, args = "MetricIntentDecision", self.decisions[payload["question"]]
        elif self.role == "report" and "ReportDecision" in self.bound_tool_names:
            name, args = (
                "ReportDecision",
                {"hypothesis_order": list(range(len(payload["allowed_report"]["hypotheses"])))},
            )
        else:
            return super()._generate(messages, stop, run_manager, **kwargs)
        assert name in self.bound_tool_names
        return ChatResult(
            generations=[
                ChatGeneration(
                    message=AIMessage(
                        content="",
                        tool_calls=[
                            {"name": name, "args": args, "id": uuid4().hex, "type": "tool_call"},
                        ],
                    )
                )
            ]
        )


def use_scripted_live_path(service, monkeypatch, decisions):
    service.settings.llm_mode = "openai"
    monkeypatch.setattr(
        service.runtime, "model", lambda role: ScriptedIntentModel(role=role, decisions=decisions)
    )


@pytest.mark.parametrize(
    "question",
    [
        "查询 R2 昨天 CPU 温度",
        "查询 R2 昨天 CPU 利用率",
        "查询 R2 昨天内存利用率",
        "查询 R2 昨天风扇转速",
        "查询 R2 昨天丢包率和 CPU 温度",
        "查询 R2 昨天每小时丢包率趋势",
        "查询全网昨天丢包率前5的接口",
        "查询 R2 昨天丢包率超过5%的接口",
        "查询 R2 丢包率同比增长率",
        "查询 R2 昨天原始采样明细",
        "查询昨天按机房统计丢包率",
    ],
)
async def test_miss_stops_every_business_branch(service, monkeypatch, question):
    def unexpected(*args, **kwargs):
        pytest.fail("A metric miss must not execute SQL or retrieval")

    monkeypatch.setattr(service.backend, "read", unexpected)
    monkeypatch.setattr(service.retriever, "search", unexpected)
    result = await service.analyze(question)
    assert result["status"] == "not_matched"
    assert result["metric_match"]["status"] == "miss"
    assert result["metric_match"]["next_layer"] == "text_to_sql"
    assert result["report_calls"] == 0
    assert result["evidence"] == {"rag": None, "sql": None}
    assert not any(e["name"].startswith("tool.") for e in result["trace"])


async def test_hit_with_no_rows_is_not_a_metric_miss(service):
    result = await service.analyze("查询 R2 2030-01-01 的丢包率")
    assert result["metric_match"]["status"] == "hit"
    assert result["status"] == "no_evidence"
    assert result["evidence"]["sql"]["status"] == "no_data"


def test_model_can_map_a_semantic_phrase_not_in_the_alias_rules():
    question = "帮我看看 R2 昨天 eth1 的数据包有多大比例没送到"
    assert build_route_plan(question, NOW, "Asia/Shanghai").metric_match.status == "miss"
    intent = loss_intent(
        metric_mentions={"packet_loss_pct": "数据包有多大比例没送到"},
        interface="eth1",
        time_expression="昨天",
    )
    plan = compile_metric_intent(intent, question, NOW, "Asia/Shanghai")
    assert plan.metric_match.status == "hit"
    assert plan.query_plan.metrics == ["packet_loss_pct"]
    assert plan.query_plan.start_utc == datetime(2026, 10, 9, 16, tzinfo=UTC)


async def test_scripted_llm_planner_uses_true_structured_output_and_executes(service, monkeypatch):
    question = "帮我看看 R2 昨天 eth1 的数据包有多大比例没送到"
    decision = loss_intent(
        metric_mentions={"packet_loss_pct": "数据包有多大比例没送到"},
        interface="eth1",
        time_expression="昨天",
    )
    use_scripted_live_path(service, monkeypatch, {question: decision.model_dump(mode="json")})
    result = await service.analyze(question)
    assert result["status"] == "completed"
    assert result["metric_match"]["planner"] == "llm"
    assert result["query_plan"]["metrics"] == ["packet_loss_pct"]
    assert result["evidence"]["sql"]["queries"][0]["rows"][0]["average_value"] == pytest.approx(
        6.06
    )
    assert [e["name"] for e in result["trace"] if e["name"].startswith("tool.")] == [
        "tool.get_schema",
        "tool.query_network_metrics",
    ]


@pytest.mark.parametrize("question", ["查询 R2 昨天 CPU 利用率", "查询 R2 昨天每小时丢包率趋势"])
async def test_server_overrules_false_llm_hit(service, monkeypatch, question):
    wrong = loss_intent(metric_mentions={"packet_loss_pct": question})
    use_scripted_live_path(service, monkeypatch, {question: wrong.model_dump(mode="json")})
    result = await service.analyze(question)
    assert result["status"] == "not_matched"
    assert result["evidence"]["sql"] is None
    assert result["report_calls"] == 0


@pytest.mark.parametrize(
    "change",
    ["device", "all", "time", "metric", "formula", "sql", "filter", "averaging", "dropped_device"],
)
async def test_ungrounded_or_untyped_model_output_never_queries(service, monkeypatch, change):
    question = "查询 R2 昨天丢包率"
    decision = loss_intent().model_dump(mode="json")
    if change == "device":
        decision["devices"] = ["R3"]
    elif change == "dropped_device":
        question = "查询 R2 和 R3 昨天丢包率"
    elif change == "all":
        decision["all_devices"] = True
    elif change == "time":
        decision["time_expression"] = "2020-01-01"
    elif change == "metric":
        decision["metrics"] = ["latency_ms"]
        decision["metric_mentions"] = {"latency_ms": "丢包率"}
    elif change in ("formula", "sql"):
        decision[change] = "SELECT password FROM mysql.user"
    elif change == "filter":
        decision["severity"] = "critical"
    else:
        decision["metric_options"] = {
            "packet_loss_pct": {"aggregation": "interface_mean", "grouping": "device"}
        }
    use_scripted_live_path(service, monkeypatch, {question: decision})
    result = await service.analyze(question)
    assert result["status"] == "failed"
    assert result["metric_match"]["status"] == "error"
    assert result["evidence"]["sql"] is None
    assert result["report_calls"] == 0
    assert "password" not in result["report"]["summary"]


async def test_live_provider_failure_does_not_fall_back_to_rule_success(service, monkeypatch):
    service.settings.llm_mode = "openai"

    async def fail(*args, **kwargs):
        raise TimeoutError("SECRET_PROVIDER_URL")

    monkeypatch.setattr(service.runtime, "invoke", fail)
    result = await service.analyze("查询 R2 昨天丢包率")
    assert result["status"] == "failed"
    assert result["metric_match"]["status"] == "error"
    assert result["evidence"]["sql"] is None
    assert "SECRET_PROVIDER_URL" not in str(result)


def test_server_does_not_accept_an_omitted_second_metric():
    question = "查询 R2 昨天丢包率和时延"
    plan = compile_metric_intent(loss_intent(), question, NOW, "UTC")
    assert plan.metric_match.status == "miss"
    assert plan.metric_match.reason_codes == ["omitted_metric"]


def test_model_declared_unsupported_operation_is_also_a_miss():
    plan = compile_metric_intent(
        loss_intent(features=["ranking"]), "查询 R2 昨天丢包率", NOW, "UTC"
    )
    assert plan.metric_match.status == "miss"


def test_llm_clarification_draft_can_resume_device_time_and_mean():
    question = "查询 R2 的丢包率"
    first = compile_metric_intent(loss_intent(), question, NOW, "UTC")
    assert first.metric_match.status == "clarify"
    second = compile_metric_intent(
        loss_intent(metric_mentions={}, devices=[], use_context=True, time_expression="昨天"),
        "昨天",
        NOW,
        "UTC",
        first,
    )
    assert second.metric_match.status == "hit"
    pending = compile_metric_intent(loss_intent(), "查询 R2 昨天设备整体平均丢包率", NOW, "UTC")
    assert pending.metric_match.status == "clarify"
    still_pending = compile_metric_intent(
        loss_intent(metric_mentions={}, devices=[], use_context=True), "昨天", NOW, "UTC", pending
    )
    assert still_pending.metric_match.status == "clarify"
    resolved = compile_metric_intent(
        loss_intent(
            metric_mentions={},
            devices=[],
            use_context=True,
            metric_options={
                "packet_loss_pct": {"aggregation": "interface_mean", "grouping": "device"}
            },
            aggregation_mentions={"packet_loss_pct": "先算每个接口均值，再按接口等权"},
        ),
        "先算每个接口均值，再按接口等权",
        NOW,
        "UTC",
        pending,
    )
    assert resolved.metric_match.status == "hit"
    assert resolved.query_plan.metric_options["packet_loss_pct"].aggregation == "interface_mean"


def test_server_recovers_known_ambiguity_even_when_model_omits_metric():
    intent = MetricIntentDecision(route="sql", disposition="hit", devices=["R2"])
    plan = compile_metric_intent(intent, "查询 R2 昨天设备整体平均丢包率", NOW, "UTC")
    assert plan.metric_match.status == "clarify"
    assert plan.query_plan.metrics == ["packet_loss_pct"]


def test_explicit_categorical_filter_is_not_silently_dropped():
    intent = MetricIntentDecision(
        route="sql",
        disposition="hit",
        metrics=["alarm_count"],
        metric_mentions={"alarm_count": "警报"},
        devices=["R2"],
    )
    plan = compile_metric_intent(intent, "数数 R2 昨天有几条 critical 警报", NOW, "UTC")
    assert plan.metric_match.status == "hit"
    assert plan.query_plan.severity == "critical"


def test_alarm_only_filters_are_not_reused_as_sample_filters():
    first = compile_metric_intent(
        MetricIntentDecision(
            route="sql",
            disposition="hit",
            metrics=["alarm_count"],
            metric_mentions={"alarm_count": "告警"},
            devices=["R2"],
            severity="critical",
        ),
        "查询 R2 昨天严重告警多少条",
        NOW,
        "UTC",
    )
    next_intent = loss_intent(use_context=True, devices=[], severity="critical")
    next_plan = compile_metric_intent(next_intent, "那同一时间丢包率呢", NOW, "UTC", first)
    assert next_plan.metric_match.status == "hit"
    assert next_plan.query_plan.severity is None


def test_negative_all_devices_is_not_authorization_to_expand_scope():
    with pytest.raises(ValueError):
        compile_metric_intent(
            loss_intent(devices=[], all_devices=True), "不要全网，查询昨天丢包率", NOW, "UTC"
        )


def test_model_cannot_hide_a_timed_data_request_in_rag():
    decision = MetricIntentDecision(route="rag", disposition="hit")
    plan = compile_metric_intent(decision, "R2 昨天 CPU 温度", NOW, "UTC")
    assert plan.metric_match.status == "miss"


def test_independent_resolve_api_has_auth_and_never_reads_business_rows(monkeypatch):
    settings = Settings(_env_file=None, api_auth_token="metric-layer-test")
    api = create_app(settings)
    headers = {"Authorization": "Bearer metric-layer-test"}
    with TestClient(api) as client:

        def unexpected(*args, **kwargs):
            pytest.fail("Resolve API must not execute a database query")

        monkeypatch.setattr(api.state.service.backend, "read", unexpected)
        assert (
            client.post("/api/v1/metrics/resolve", json={"message": "查询R2昨天丢包率"}).status_code
            == 401
        )
        for question, expected in [
            ("查询 R2 昨天丢包率", "hit"),
            ("查询 R2 丢包率", "clarify"),
            ("查询 R2 昨天 CPU 温度", "miss"),
        ]:
            response = client.post(
                "/api/v1/metrics/resolve", json={"message": question}, headers=headers
            )
            assert response.status_code == 200
            assert response.json()["metric_match"]["status"] == expected
        assert (
            client.post(
                "/api/v1/metrics/resolve", json={"message": "test", "scope": {}}, headers=headers
            ).status_code
            == 422
        )


def test_resolve_api_model_failure_is_503_not_a_fake_miss(monkeypatch):
    settings = Settings(_env_file=None, api_auth_token="metric-layer-test")
    api = create_app(settings)
    with TestClient(api) as client:

        async def fail(*args, **kwargs):
            raise ValueError("SECRET_PROVIDER_URL")

        monkeypatch.setattr(api.state.service.runtime, "plan_request", fail)
        response = client.post(
            "/api/v1/metrics/resolve",
            json={"message": "查询 R2 昨天丢包率"},
            headers={"Authorization": "Bearer metric-layer-test"},
        )
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "metric_planning_failed"
        assert "SECRET_PROVIDER_URL" not in response.text


def test_metric_context_is_not_inherited_by_a_new_knowledge_question():
    previous = compile_metric_intent(loss_intent(), "查询 R2 昨天丢包率", NOW, "UTC")
    rag = MetricIntentDecision(route="rag", disposition="hit", use_context=True)
    plan = compile_metric_intent(rag, "OSPF 原理是什么", NOW, "UTC", previous)
    assert plan.metric_match.status == "not_applicable"
    assert plan.query_plan is None


@pytest.mark.parametrize("field", ["tenant_id", "scope", "formula", "sql"])
def test_intent_schema_forbids_authorization_and_sql(field):
    data = loss_intent().model_dump(mode="json")
    data[field] = "untrusted"
    with pytest.raises(ValidationError):
        MetricIntentDecision.model_validate(data)


def test_planner_catalog_contains_semantics_but_not_connection_or_base_tables():
    catalog = planner_catalog()
    assert len(catalog["metrics"]) == 9
    serialized = json.dumps(catalog)
    assert "MYSQL_READONLY_URI" not in serialized
    assert "v_interface_metrics" not in serialized
    assert "network_metrics" not in serialized
    assert catalog["capabilities"]["sql_cache_enabled"] is False


def test_grounded_device_alias_and_deterministic_calendar_time():
    question = "查询二号路由器昨日往返耗时"
    intent = MetricIntentDecision(
        route="sql",
        disposition="hit",
        metrics=["latency_ms"],
        metric_mentions={"latency_ms": "往返耗时"},
        devices=["R2"],
        time_expression="昨日",
    )
    plan = compile_metric_intent(intent, question, NOW, "Asia/Shanghai")
    assert plan.metric_match.status == "hit"
    assert plan.query_plan.devices == ["R2"]
    assert resolve_window("上周", NOW, "Asia/Shanghai")[0] == datetime(2026, 9, 27, 16, tzinfo=UTC)
    assert (
        resolve_window("过去两小时", NOW, "UTC")[1] - resolve_window("过去两小时", NOW, "UTC")[0]
    ).total_seconds() == 7200
    assert resolve_window("昨天 12:00 到 18:00", NOW, "Asia/Shanghai")[0] == datetime(
        2026, 10, 10, 4, tzinfo=UTC
    )
