from datetime import UTC, datetime
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field
from sqlglot import exp

from app.agents.mock_model import MockNetworkModel
from app.schemas.generated_sql import GeneratedSqlDraft, SqlRequestContext
from app.schemas.models import Scope
from app.security.generated_sql_guard import SqlContextMissing, validate_generated_sql
from app.security.sql_guard import SqlRejected, validate_sql
from app.storage.fixtures import demo_records
from app.tools.generated_sql import GeneratedSqlService

NOW = datetime(2026, 10, 11, 9, tzinfo=UTC)
QUESTION = "查询 R2 昨天按平均丢包率排名前3的接口"
RANK_SQL = "SELECT hostname, interface_name, AVG(packet_loss_pct) AS average_value FROM v_interface_metrics GROUP BY hostname, interface_name ORDER BY average_value DESC LIMIT 3"


def draft(sql=RANK_SQL, **values):
    return GeneratedSqlDraft(disposition="query", sql=sql, **values)


def context():
    return SqlRequestContext(
        devices=["R2"],
        start_utc=datetime(2026, 10, 10, tzinfo=UTC),
        end_utc=datetime(2026, 10, 11, tzinfo=UTC),
    )


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM v_alarm_events",
        "SELECT * FROM v_interface_metrics",
        "SELECT hostname FROM v_device_status; SELECT hostname FROM v_device_status",
        "SELECT password FROM mysql.user",
        "SELECT root_cause FROM network_incidents",
        "SELECT SLEEP(1) AS delay FROM v_device_status",
        "SELECT LOAD_FILE('/etc/passwd') AS content FROM v_device_status",
        "SELECT hostname FROM v_device_status FOR UPDATE",
        "SELECT hostname INTO OUTFILE '/tmp/data' FROM v_device_status",
        "WITH t AS (SELECT hostname FROM v_device_status) SELECT hostname FROM t",
        "SELECT a.hostname FROM v_device_status a JOIN v_alarm_events b ON a.device_id=b.device_id",
        "SELECT hostname FROM v_device_status UNION SELECT hostname FROM v_device_status",
        "SELECT hostname, ROW_NUMBER() OVER (ORDER BY hostname) AS n FROM v_device_status",
        "SELECT 99 AS fabricated FROM v_device_status",
        "SELECT SUM(packet_loss_pct) AS fabricated FROM v_interface_metrics",
        "SELECT COALESCE(AVG(packet_loss_pct), 0) AS fabricated FROM v_interface_metrics",
        "SELECT AVG(packet_loss_pct)*100 AS fabricated FROM v_interface_metrics",
        "SELECT hostname AS tenant_id FROM v_device_status",
        "SELECT hostname AS duplicate, status AS duplicate FROM v_device_status",
        "SELECT hostname FROM v_device_status WHERE hostname='R3'",
        "SELECT hostname FROM v_device_status WHERE hostname=:req_device_0",
        "SELECT hostname FROM v_device_status WHERE hostname=:acl_tenant",
        "SELECT hostname FROM v_device_status /* comment */",
        "SELECT DATE_FORMAT(sample_time, '%s') AS bucket FROM v_interface_metrics",
        "SELECT DATE_FORMAT(hostname, '%Y-%m-%d') AS bucket FROM v_device_status",
        "SELECT hostname FROM v_interface_metrics WHERE packet_loss_pct>50",
    ],
)
def test_bad_generated_sql_rejected(sql):
    with pytest.raises(SqlRejected):
        validate_generated_sql(sql, context(), 200)


def test_utc_bucket_is_only_added_to_the_new_sql_dialect():
    sql = "SELECT DATE_FORMAT(sample_time, '%Y-%m-%d %H:00:00') AS bucket_utc, AVG(packet_loss_pct) AS average_value FROM v_interface_metrics GROUP BY bucket_utc ORDER BY bucket_utc"
    with pytest.raises(SqlRejected):
        validate_sql(sql)
    parsed = validate_generated_sql(sql, context(), 200)
    assert "STRFTIME" in parsed.sql(dialect="sqlite")
    assert isinstance(parsed, exp.Select)


def test_request_constraints_are_injected_even_without_model_where(service, scope):
    sql_service = GeneratedSqlService(service.query_service)
    prepared = sql_service.prepare(draft(), QUESTION, NOW, "Asia/Shanghai")
    sql, parameters, request, _ = prepared
    assert request.devices == ["R2"]
    assert "req_device_0" in sql.sql()
    assert parameters["req_device_0"] == "R2"
    result = sql_service.execute(prepared, scope)
    assert result.status == "ok"
    assert {row["hostname"] for row in result.queries[0].rows} == {"R2"}
    assert result.queries[0].verification_status == "unverified"
    assert result.queries[0].rows[0]["average_value"] == pytest.approx(6.06)


def test_model_or_cannot_widen_request_scope(service, scope):
    sql_service = GeneratedSqlService(service.query_service)
    sql = RANK_SQL.replace(" GROUP BY", " WHERE 1=1 OR 1=1 GROUP BY")
    result = sql_service.execute(sql_service.prepare(draft(sql), QUESTION, NOW, "UTC"), scope)
    assert {r["hostname"] for r in result.queries[0].rows} == {"R2"}


@pytest.mark.parametrize(
    "changes",
    [
        {"devices": ["R3"]},
        {"all_devices": True},
        {"interface": "eth9"},
        {"severity": "critical"},
        {"parameters": {"acl_tenant": "other"}},
        {"parameters": {"req_device_0": "R99"}},
        {"parameters": {"device_0": "R3"}},
    ],
)
def test_no_model_invented_scope_filters_or_reserved_values(service, changes):
    with pytest.raises(SqlRejected):
        GeneratedSqlService(service.query_service).prepare(draft(**changes), QUESTION, NOW, "UTC")


def test_other_requested_metric_is_not_silently_substituted(service):
    with pytest.raises(SqlRejected):
        GeneratedSqlService(service.query_service).prepare(
            draft(RANK_SQL.replace("packet_loss_pct", "latency_ms")), QUESTION, NOW, "UTC"
        )


def test_explicit_mean_cannot_be_changed_to_a_maximum(service):
    with pytest.raises(SqlRejected):
        GeneratedSqlService(service.query_service).prepare(
            draft(RANK_SQL.replace("AVG(", "MAX(")), QUESTION, NOW, "UTC"
        )


def test_model_time_prose_is_not_used_as_query_boundaries(service, scope):
    generated = GeneratedSqlService(service.query_service)
    prepared = generated.prepare(
        draft(time_expression="UTC 2020-01-01 to 2020-01-02"), QUESTION, NOW, "UTC"
    )
    assert prepared[1]["req_start"].startswith("2026-10-10")
    assert prepared[2].ignored_model_time_expression is True
    result = generated.execute(prepared, scope)
    assert result.status == "ok"
    assert result.queries[0].rows[0]["average_value"] == pytest.approx(6.06)


def test_missing_device_context_is_not_an_all_device_request(service):
    generated = GeneratedSqlService(service.query_service)
    with pytest.raises(SqlContextMissing) as caught:
        generated.prepare(draft(), "查询昨天按平均丢包率排名前3的接口", NOW, "UTC")
    partial = caught.value.context
    assert partial.devices == []
    assert partial.all_devices is False
    assert partial.start_utc is not None
    with pytest.raises(SqlRejected):
        generated.prepare(
            draft(all_devices=True, use_context=True), "还是查昨天", NOW, "UTC", partial
        )


async def test_generated_sql_clarification_retains_only_known_request_slots(service, monkeypatch):
    service.settings.text_to_sql_enabled = True
    original = service.runtime.invoke
    payloads = []

    async def respond(role, payload, schema, tools=()):
        if payload.get("phase") == "generate_sql":
            payloads.append(payload)
            return {
                "structured_response": draft(
                    use_context=bool(payload.get("previous_request_context"))
                )
            }
        return await original(role, payload, schema, tools)

    monkeypatch.setattr(service.runtime, "invoke", respond)
    from langgraph.checkpoint.memory import InMemorySaver

    from app.graph.workflow import build_graph
    from app.observability.tracing import RequestTrace
    from app.schemas.context import InvocationContext

    graph = build_graph(service.runtime, service.settings, InMemorySaver())
    config = {"configurable": {"thread_id": "generated-clarification"}}

    async def ask(question, request):
        return await graph.ainvoke(
            {
                "question": question,
                "timezone": "UTC",
                "request_id": request,
                "messages": [{"role": "user", "content": question}],
            },
            config=config,
            context=InvocationContext(Scope(), RequestTrace(request)),
        )

    first = await ask("查询 R2 按平均丢包率排名前3的接口", "first")
    assert first["final_report"]["status"] == "needs_clarification"
    assert first["generated_sql_result"]["request_context"]["devices"] == ["R2"]
    second = await ask("昨天", "second")
    assert second["generated_sql_result"]["status"] == "ok"
    assert second["generated_sql_result"]["queries"][0]["rows"][0]["hostname"] == "R2"
    assert payloads[-1]["previous_request_context"]["devices"] == ["R2"]


def test_raw_samples_keep_null_observations_while_averages_exclude_them(service, scope):
    records = demo_records()
    extra = dict(records["network_metrics"][5])
    extra.update(metric_id=250, packet_loss_pct=None)
    records["network_metrics"].append(extra)
    service.backend.records_factory = lambda: records
    generated = GeneratedSqlService(service.query_service)
    sql = "SELECT hostname, sample_time, packet_loss_pct FROM v_interface_metrics ORDER BY sample_time"
    raw = generated.execute(
        generated.prepare(draft(sql), "查询 R2 昨天原始丢包率采样明细", NOW, "UTC"), scope
    )
    assert raw.status == "ok"
    assert len(raw.queries[0].rows) == 6
    assert any(row["packet_loss_pct"] is None for row in raw.queries[0].rows)
    aggregate = generated.execute(generated.prepare(draft(), QUESTION, NOW, "UTC"), scope)
    assert aggregate.queries[0].rows[0]["average_value"] == pytest.approx(6.06)


def test_empty_scalar_aggregate_is_not_a_zero_measurement(service, scope):
    generated = GeneratedSqlService(service.query_service)
    scalar = draft("SELECT AVG(packet_loss_pct) AS average_value FROM v_interface_metrics")
    result = generated.execute(
        generated.prepare(scalar, "查询 R2 2030-01-01 平均丢包率", NOW, "UTC"), scope
    )
    assert result.status == "no_data"
    assert result.queries[0].rows == [{"average_value": None}]


class ScriptedSqlModel(MockNetworkModel):
    response: dict = Field(default_factory=dict)

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        assert "GeneratedSqlDraft" in self.bound_tool_names
        return ChatResult(
            generations=[
                ChatGeneration(
                    message=AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "name": "GeneratedSqlDraft",
                                "args": self.response,
                                "id": uuid4().hex,
                                "type": "tool_call",
                            },
                        ],
                    )
                )
            ]
        )


async def test_live_code_path_uses_real_structured_tool_loop_not_metric_templates(
    service, scope, monkeypatch
):
    service.settings.llm_mode = "openai"
    monkeypatch.setattr(
        service.runtime,
        "model",
        lambda role: ScriptedSqlModel(role=role, response=draft().model_dump(mode="json")),
    )
    from app.observability.tracing import RequestTrace

    result = await service.runtime.generated_sql(
        QUESTION, scope, "UTC", RequestTrace("sql-structured")
    )
    assert result.status == "ok"
    assert result.planner == "llm"
    assert result.generation_attempted is True
    assert result.queries[0].output_units["average_value"] == "%"


async def test_invalid_sql_has_one_bounded_repair_and_zero_database_execution(
    service, scope, monkeypatch
):
    service.settings.llm_mode = "openai"
    calls = []

    def model(role):
        calls.append(role)
        return ScriptedSqlModel(
            role=role, response=draft("DELETE FROM v_alarm_events").model_dump(mode="json")
        )

    monkeypatch.setattr(service.runtime, "model", model)

    def unexpected(*args, **kwargs):
        pytest.fail("Rejected drafts must never access the database")

    monkeypatch.setattr(service.backend, "read", unexpected)
    from app.observability.tracing import RequestTrace

    result = await service.runtime.generated_sql(QUESTION, scope, "UTC", RequestTrace("sql-reject"))
    assert result.status == "forbidden"
    assert result.repair_attempts == 1
    assert len(calls) == 2


async def test_database_timeout_is_not_retried_or_replanned(service, scope, monkeypatch):
    service.settings.llm_mode = "openai"
    monkeypatch.setattr(
        service.runtime,
        "model",
        lambda role: ScriptedSqlModel(role=role, response=draft().model_dump(mode="json")),
    )
    calls = []

    def timeout(*args, **kwargs):
        calls.append(1)
        raise TimeoutError("SECRET_CONNECTION_STRING")

    monkeypatch.setattr(service.backend, "read", timeout)
    from app.observability.tracing import RequestTrace

    result = await service.runtime.generated_sql(
        QUESTION, scope, "UTC", RequestTrace("sql-timeout")
    )
    assert result.status == "timeout"
    assert len(calls) == 1
    assert result.repair_attempts == 0
    assert "SECRET_CONNECTION_STRING" not in result.model_dump_json()


def test_backend_scope_is_still_enforced(service):
    generated = GeneratedSqlService(service.query_service)
    prepared = generated.prepare(draft(), QUESTION, NOW, "UTC")
    assert generated.execute(prepared, Scope(device_ids=(3,))).status == "forbidden"
    assert generated.execute(prepared, Scope(device_ids=())).status == "forbidden"


@pytest.mark.parametrize(
    "question",
    [
        "查询 R2 昨天按平均丢包率排名前3的接口",
        "查询 R2 昨天每小时丢包率趋势",
        "查询 R2 昨天平均丢包率超过5%的接口",
        "查询 R2 昨天按告警类型统计数量",
        "查询 R2 昨天原始丢包率采样明细",
    ],
)
async def test_graph_falls_back_only_from_metric_miss(service, question):
    service.settings.text_to_sql_enabled = True
    result = await service.analyze(question)
    assert result["metric_match"]["status"] == "miss"
    assert result["query_path"] == "text_to_sql"
    assert result["status"] == "partial"
    assert result["report"]["requires_review"] is True
    assert result["report"]["verification_status"] == "unverified"
    assert result["report"]["generation_mode"] == "model_sql"
    evidence = result["evidence"]["generated_sql"]
    assert evidence["status"] == "ok", evidence
    assert evidence["cache_used"] is False
    assert evidence["queries"][0]["row_count"] > 0
    assert "SQL 示例缓存" not in evidence["queries"][0]["sql"]
    assert result["report_calls"] == 1


@pytest.mark.parametrize(
    "question",
    [
        "查询 R2 昨天 CPU 温度",
        "查询 R2 昨天 CPU 利用率和丢包率",
        "查询 R2 昨天设备状态",
        "查询 R2 昨天 P95 RTT",
    ],
)
async def test_fallback_does_not_fabricate_missing_sources(service, monkeypatch, question):
    service.settings.text_to_sql_enabled = True

    def unexpected(*args, **kwargs):
        pytest.fail("Missing source data must not run SQL")

    monkeypatch.setattr(service.backend, "read", unexpected)
    result = await service.analyze(question)
    assert result["status"] == "not_matched"
    assert result["evidence"]["generated_sql"]["status"] == "unavailable"
    assert not result["evidence"]["generated_sql"]["queries"]


@pytest.mark.parametrize(
    "question",
    [
        "查询 R2 昨天丢包率",
        "查询 R2 的丢包率",
        "查询 R99 昨天告警",
        "查询 R2 2030-01-01 丢包率",
        "删除所有告警数据",
    ],
)
async def test_hit_clarify_forbidden_empty_never_trigger_fallback(service, monkeypatch, question):
    service.settings.text_to_sql_enabled = True

    async def unexpected(*args, **kwargs):
        pytest.fail("Only a metric miss may trigger generated SQL")

    monkeypatch.setattr(service.runtime, "generated_sql", unexpected)
    result = await service.analyze(question)
    assert "generated_sql" not in result["evidence"]


async def test_generated_trend_respects_row_budget_and_utc(service):
    service.settings.text_to_sql_enabled = True
    service.settings.sql_max_rows = 2
    result = await service.analyze("查询 R2 昨天每小时丢包率趋势")
    evidence = result["evidence"]["generated_sql"]["queries"][0]
    assert evidence["row_count"] == 2
    assert evidence["truncated"]
    assert all("bucket_utc" in r for r in evidence["rows"])


@pytest.mark.mysql
def test_real_mysql_generated_hourly_bucket(mysql_service, scope):
    sql = "SELECT DATE_FORMAT(sample_time, '%Y-%m-%d %H:00:00') AS bucket_utc, AVG(packet_loss_pct) AS average_value FROM v_interface_metrics GROUP BY bucket_utc ORDER BY bucket_utc"
    generated = GeneratedSqlService(mysql_service.query_service)
    result = generated.execute(
        generated.prepare(draft(sql), "查询 R2 昨天每小时丢包率趋势", NOW, "UTC"), scope
    )
    assert result.status == "ok"
    assert len(result.queries[0].rows) == 5
