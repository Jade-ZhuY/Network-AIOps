import asyncio
from copy import deepcopy
from datetime import UTC, datetime

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import Settings
from app.main import create_app
from app.schemas.generated_sql import GeneratedSqlDraft
from app.schemas.metric_review import PublishMetricInput, QueryReviewInput
from app.schemas.models import Scope
from app.security.auth import Principal, current_principal
from app.security.sql_guard import SqlRejected
from app.semantics.reviewed_metrics import MetricReviewService, compile_contract
from app.storage.fixtures import demo_records
from app.storage.metric_governance import MetricGovernanceStore
from app.storage.sessions import MemorySessions, SessionBusy
from app.tools.generated_sql import GeneratedSqlService

HEADERS = {"Authorization": "Bearer engineer-review-token"}
QUESTION = "查询 R2 昨天按平均丢包率排名前3的接口"
NOW = datetime(2026, 10, 11, 9, tzinfo=UTC)


def actor_dependency(actor):
    def dependency():
        return actor

    return dependency


@pytest.fixture
def review_app():
    settings = Settings(
        _env_file=None,
        persistence_backend="memory",
        llm_mode="mock",
        data_backend="mock",
        text_to_sql_enabled=True,
        api_auth_token="engineer-review-token",
        api_admin_token="admin-review-token",
        enable_demo_api=False,
    )
    app = create_app(settings)
    with TestClient(app) as client:
        yield app, client


def source_query(client, question=QUESTION):
    sid = client.post("/api/v1/sessions", headers=HEADERS, json={}).json()["session_id"]
    response = client.post(
        "/api/v1/chat", headers=HEADERS, json={"session_id": sid, "message": question}
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["query_path"] == "text_to_sql", result
    query = result["evidence"]["generated_sql"]["queries"][0]
    path = f"/api/v1/requests/{result['request_id']}/queries/{query['query_id']}"
    return result, query, path


def approve(client, path, expected_revision=0, **extra):
    response = client.put(
        path + "/review",
        headers=HEADERS,
        json={
            "verdict": "approved",
            "comment": "核对过采样均值、排序和单位",
            "expected_revision": expected_revision,
            **extra,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def publish(client, path, **extra):
    return client.post(
        path + "/metric",
        headers=HEADERS,
        json={
            "label": "接口丢包排名前三",
            "aliases": ["丢包Top3"],
            "description": "按设备和接口计算采样等权平均丢包率，降序返回前三项。",
            "review_revision": 1,
            "confirm_contract": True,
            **extra,
        },
    )


def named_query(client, sid, question="查询指标「接口丢包排名前三」 R3 昨天"):
    response = client.post(
        "/api/v1/chat", headers=HEADERS, json={"session_id": sid, "message": question}
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_review_publish_and_first_layer_reuse_without_model_or_cached_rows(review_app, monkeypatch):
    app, client = review_app
    original, query, path = source_query(client)
    assert original["query_reviews"][query["query_id"]]["verdict"] == "pending"
    assert publish(client, path).status_code == 409
    review = approve(client, path)
    assert review["revision"] == 1 and review["history"][0]["verdict"] == "approved"
    candidate = client.get(path + "/metric-candidate", headers=HEADERS).json()
    assert candidate["eligible"]
    assert "req_device_0" not in candidate["contract"]["sql"]
    assert "req_start" not in candidate["contract"]["sql"]
    assert "R2" not in candidate["contract"]["sql"]
    published = publish(client, path)
    assert published.status_code == 201, published.text
    metric = published.json()
    assert metric["version"] == 1 and metric["active"]
    assert metric["contract"]["output_units"]["average_value"] == "%"
    assert "rows" not in metric["contract"]
    assert publish(client, path).json()["metric_id"] == metric["metric_id"]
    assert len(client.get("/api/v1/metrics/reviewed", headers=HEADERS).json()["metrics"]) == 1
    catalog = client.get("/api/v1/metrics", headers=HEADERS).json()
    assert len(catalog["metrics"]) == 9
    assert catalog["reviewed_metrics"][0]["metric_id"] == metric["metric_id"]

    async def no_model(*args, **kwargs):
        pytest.fail("Named approved metric must not invoke a planning/SQL LLM")

    monkeypatch.setattr(app.state.service.runtime, "invoke", no_model)
    result = named_query(client, original["session_id"])
    assert result["query_path"] == "reviewed_metric"
    assert result["metric_match"]["status"] == "hit"
    assert result["metric_match"]["matched_reviewed_metrics"] == [metric["metric_id"]]
    assert result["status"] == "completed", result
    evidence = result["evidence"]["reviewed_metric"]["queries"][0]
    assert {r["hostname"] for r in evidence["rows"]} == {"R3"}
    assert evidence["parameters"]["req_device_0"] == "R3"
    assert evidence["verification_status"] == "human_reviewed"
    assert evidence["definition_hash"] == metric["definition_hash"]
    assert not result["report"]["requires_review"]
    assert "generated_sql" not in result["evidence"]
    resolved = client.post(
        "/api/v1/metrics/resolve", headers=HEADERS, json={"message": "查询指标「丢包Top3」 R2 今天"}
    ).json()
    assert resolved["metric_match"]["status"] == "hit"
    assert resolved["reviewed_metric_plan"]["metric_id"] == metric["metric_id"]

    before = named_query(client, original["session_id"], "查询指标「丢包Top3」 R2 昨天")
    records = demo_records()
    for row in records["network_metrics"]:
        if row["device_id"] == 2:
            row["packet_loss_pct"] = 21.5
    app.state.service.backend.records_factory = lambda: records
    after = named_query(client, original["session_id"], "查询指标「丢包Top3」 R2 昨天")
    assert before["evidence"]["reviewed_metric"]["queries"][0]["rows"][0]["average_value"] != 21.5
    assert after["evidence"]["reviewed_metric"]["queries"][0]["rows"][0]["average_value"] == 21.5


def test_review_history_display_and_revocation_are_atomic(review_app):
    _, client = review_app
    original, query, path = source_query(client)
    approve(client, path)
    metric = publish(client, path).json()
    updated = client.put(
        path + "/review",
        headers=HEADERS,
        json={
            "verdict": "changes_requested",
            "comment": "统计基准需要重新确认",
            "expected_revision": 1,
        },
    )
    assert updated.status_code == 200
    review = updated.json()
    assert review["revision"] == 2 and len(review["history"]) == 2
    assert client.get("/api/v1/metrics/reviewed", headers=HEADERS).json()["metrics"] == []
    blocked = named_query(client, original["session_id"])
    assert blocked["status"] == "needs_clarification"
    assert blocked["query_path"] != "text_to_sql"
    assert publish(client, path).status_code == 409
    messages = client.get(
        f"/api/v1/sessions/{original['session_id']}/messages", headers=HEADERS
    ).json()["messages"]
    stored = messages[0]["response"]
    assert stored["query_reviews"][query["query_id"]]["verdict"] == "changes_requested"
    assert not stored["query_reviews"][query["query_id"]]["published_metric"]["active"]
    assert stored["report"]["verification_status"] == "unverified"  # origin is not rewritten
    approve(client, path, 2)
    assert client.get("/api/v1/metrics/reviewed", headers=HEADERS).json()["metrics"] == []
    next_version = publish(client, path, review_revision=3).json()
    assert next_version["metric_id"] == metric["metric_id"] and next_version["version"] == 2
    assert len(next_version["versions"]) == 2


def test_owner_tenant_scope_and_no_client_sql_or_authorization_override(review_app):
    app, client = review_app
    original, query, path = source_query(client)
    assert client.get(path + "/review").status_code == 401
    assert (
        client.get(
            path + "/review", headers={"Authorization": "Bearer admin-review-token"}
        ).status_code
        == 404
    )
    approve(client, path)
    publish(client, path)
    for denied in (
        Principal("other", "engineer", Scope()),
        Principal("netops-engineer", "engineer", Scope(tenant_id="other")),
        Principal("netops-engineer", "engineer", Scope(device_ids=(2,))),
    ):
        app.dependency_overrides[current_principal] = actor_dependency(denied)
        assert client.get(path + "/review", headers=HEADERS).status_code == 404
        assert (
            client.put(
                path + "/review",
                headers=HEADERS,
                json={"verdict": "approved", "expected_revision": 0},
            ).status_code
            == 404
        )
        assert publish(client, path).status_code == 404
        assert client.get("/api/v1/metrics/reviewed", headers=HEADERS).json()["metrics"] == []
    app.dependency_overrides.clear()
    assert (
        client.put(
            path + "/review",
            headers=HEADERS,
            json={"verdict": "approved", "expected_revision": 1, "scope": {}},
        ).status_code
        == 422
    )
    assert publish(client, path, sql="SELECT hostname FROM v_device_status").status_code == 422
    assert publish(client, path, confirm_contract=False).status_code == 422
    assert (
        client.get(
            path.replace(query["query_id"], "missing") + "/review", headers=HEADERS
        ).status_code
        == 404
    )


def test_stale_review_and_changed_evidence_do_not_publish(review_app):
    app, client = review_app
    original, query, path = source_query(client)
    approve(client, path)
    assert (
        client.put(
            path + "/review",
            headers=HEADERS,
            json={"verdict": "changes_requested", "expected_revision": 0},
        ).status_code
        == 409
    )
    source = app.state.service.sessions.requests[original["request_id"]]["response"]
    source["evidence"]["generated_sql"]["queries"][0]["rows"][0]["average_value"] = 99
    assert client.get(path + "/review", headers=HEADERS).json()["evidence_changed"]
    assert publish(client, path).status_code == 409
    review = approve(client, path, 1)
    assert review["revision"] == 2
    assert publish(client, path, review_revision=1).status_code == 409
    assert publish(client, path, review_revision=2).status_code == 201


@pytest.mark.parametrize(
    "question", ["查询 R2 2030-01-01 按平均丢包率排名前3的接口", "查询 R2 昨天每小时丢包率趋势"]
)
def test_empty_or_truncated_query_is_not_publishable(review_app, question):
    app, client = review_app
    if "每小时" in question:
        app.state.service.settings.sql_max_rows = 1
    _, _, path = source_query(client, question)
    approve(client, path)
    assert not client.get(path + "/metric-candidate", headers=HEADERS).json()["eligible"]
    assert publish(client, path).status_code == 409


@pytest.mark.parametrize(
    "extra",
    [
        {"label": "丢包率"},
        {"aliases": ["丢包率"]},
        {"aliases": ["接口丢包排名前三"]},
        {"aliases": ["A", "a"]},
    ],
)
def test_published_names_do_not_collide_with_builtin_or_each_other(review_app, extra):
    _, client = review_app
    _, _, path = source_query(client)
    approve(client, path)
    assert publish(client, path, **extra).status_code == 409


def test_duplicate_metric_name_and_explicit_withdrawal(review_app):
    _, client = review_app
    original, _, first = source_query(client)
    approve(client, first)
    metric = publish(client, first).json()
    _, _, second = source_query(client)
    approve(client, second)
    assert publish(client, second).status_code == 409
    endpoint = "/api/v1/metrics/reviewed/" + metric["metric_id"]
    assert client.delete(endpoint + "?version=999", headers=HEADERS).status_code == 409
    assert client.delete(endpoint + "?version=1", headers=HEADERS).status_code == 200
    assert named_query(client, original["session_id"])["status"] == "needs_clarification"
    assert (
        len(
            client.get("/api/v1/metrics/reviewed?include_inactive=true", headers=HEADERS).json()[
                "metrics"
            ]
        )
        == 1
    )
    assert publish(client, second).status_code == 201


@pytest.mark.parametrize(
    "suffix",
    [
        "",
        " R2",
        " 昨天",
        " R2 昨天超过10%",
        " R2 昨天每小时",
        " R2 昨天，再查 CPU",
        " R2 昨天 OR 1=1",
        " R2 昨天 eth1 eth2",
        " R2 昨天 今天",
        " R2 昨天 2026-10-10",
        " R2 全网 昨天",
    ],
)
def test_named_metric_requires_explicit_filters_and_does_not_ignore_modifiers(
    review_app, monkeypatch, suffix
):
    app, client = review_app
    original, _, path = source_query(client)
    approve(client, path)
    publish(client, path)

    async def unexpected(*args, **kwargs):
        pytest.fail("Invalid named invocation must stop before any model fallback")

    monkeypatch.setattr(app.state.service.runtime, "invoke", unexpected)
    result = named_query(client, original["session_id"], "查询指标「接口丢包排名前三」" + suffix)
    assert result["status"] == "needs_clarification", result
    assert not result["evidence"].get("reviewed_metric")
    assert not result["evidence"].get("generated_sql")


def test_named_metric_applies_new_dates_and_acl_and_does_not_leak_prior_evidence(review_app):
    _, client = review_app
    original, _, path = source_query(client)
    approve(client, path)
    publish(client, path)
    denied = named_query(client, original["session_id"], "查询指标「接口丢包排名前三」 R99 昨天")
    assert denied["status"] == "failed"
    assert denied["evidence"]["reviewed_metric"]["status"] == "forbidden"
    empty = named_query(
        client, original["session_id"], "查询指标「接口丢包排名前三」 R2 2030-01-01"
    )
    assert empty["status"] == "no_evidence"
    assert empty["report"]["facts"] == []
    all_devices = named_query(
        client, original["session_id"], "查询指标「接口丢包排名前三」 全网 昨天"
    )
    assert all_devices["status"] == "completed"
    normal = named_query(client, original["session_id"], "查询 R2 昨天丢包率")
    assert normal["status"] == "completed" and normal["query_path"] == "metrics"
    assert not normal["evidence"].get("reviewed_metric")
    knowledge = named_query(client, original["session_id"], "OSPF 是什么？")
    assert knowledge["route"] == "rag" and not knowledge["evidence"].get("reviewed_metric")


def test_fixed_threshold_is_a_definition_not_old_user_parameter_cache(review_app):
    _, client = review_app
    original, _, path = source_query(client, "查询 R2 昨天平均丢包率超过5%的接口")
    approve(client, path)
    metric = publish(client, path, label="高丢包接口", aliases=[]).json()
    assert metric["contract"]["parameters"] == {"value_0": 5}
    result = named_query(client, original["session_id"], "查询指标「高丢包接口」 R2 昨天")
    assert result["status"] == "completed", result
    query = result["evidence"]["reviewed_metric"]["queries"][0]
    assert query["parameters"]["value_0"] == 5
    assert all(r["average_value"] > 5 for r in query["rows"])


def test_review_retry_is_idempotent_and_does_not_withdraw_published_metric(review_app):
    _, client = review_app
    _, _, path = source_query(client)
    first = approve(client, path)
    publish(client, path)
    second = approve(client, path, 1)
    assert second["revision"] == first["revision"] == 1
    assert len(client.get("/api/v1/metrics/reviewed", headers=HEADERS).json()["metrics"]) == 1


def test_reviewed_metric_is_independent_of_sql_generation_flag_and_resolve_is_readonly(
    review_app, monkeypatch
):
    app, client = review_app
    original, _, path = source_query(client)
    approve(client, path)
    publish(client, path)
    app.state.service.settings.text_to_sql_enabled = False
    assert named_query(client, original["session_id"])["status"] == "completed"

    def unexpected(*args):
        pytest.fail("Resolving a named metric must not execute SQL")

    monkeypatch.setattr(app.state.service.backend, "read", unexpected)
    response = client.post(
        "/api/v1/metrics/resolve", headers=HEADERS, json={"message": "查询指标「丢包Top3」 R2 昨天"}
    )
    assert response.status_code == 200 and response.json()["metric_match"]["status"] == "hit"


async def test_withdrawal_between_planning_and_execution_stops_the_old_plan(service):
    from app.schemas.metric_review import ReviewedMetricPlan

    sessions = MemorySessions()
    actor = Principal("a", "engineer", Scope())
    manager = MetricReviewService(sessions, service.query_service, service.settings)
    # Resolve/execute is tested through the real API above; here model an immutable
    # checkpoint plan after its metric has already been removed from the catalog.
    plan = ReviewedMetricPlan(
        metric_id="withdrawn",
        version=1,
        definition_hash="old",
        label="旧指标",
        request_context={"devices": ["R2"]},
    )
    result = await manager.execute(actor, plan)
    assert result.status == "clarify" and not result.queries


def test_governance_storage_errors_are_not_fake_saved_reviews(review_app, monkeypatch):
    from app.storage.metric_governance import GovernanceStorageUnavailable

    app, client = review_app
    _, _, path = source_query(client)

    async def failed(*args):
        raise GovernanceStorageUnavailable

    monkeypatch.setattr(app.state.service.metric_reviews.store, "read", failed)
    response = client.get(path + "/review", headers=HEADERS)
    assert response.status_code == 503
    assert "PostgreSQL" in response.json()["detail"]


def test_promoted_definition_survives_source_session_deletion_without_old_rows(review_app):
    _, client = review_app
    original, _, path = source_query(client)
    approve(client, path)
    publish(client, path)
    assert (
        client.delete("/api/v1/sessions/" + original["session_id"], headers=HEADERS).status_code
        == 204
    )
    assert client.get(path + "/review", headers=HEADERS).status_code == 404
    sid = client.post("/api/v1/sessions", headers=HEADERS, json={}).json()["session_id"]
    assert named_query(client, sid)["status"] == "completed"


async def test_atomic_governance_transactions_and_isolation():
    sessions = MemorySessions()
    store = MetricGovernanceStore(sessions)
    actor = Principal("a", "engineer", Scope())
    try:
        async with store.transaction(actor) as document:
            document["reviews"]["x"] = {"value": 1}
            raise ValueError
    except ValueError:
        pass
    assert (await store.read(actor))["reviews"] == {}

    async def write(value):
        async with store.transaction(actor) as document:
            document["reviews"][str(value)] = value
            await asyncio.sleep(0.001)

    await asyncio.gather(*(write(n) for n in range(4)))
    restored = MetricGovernanceStore(sessions)
    assert len((await restored.read(actor))["reviews"]) == 4
    assert not (await restored.read(Principal("b", "engineer", Scope())))["reviews"]
    snapshot = await restored.read(actor)
    snapshot["reviews"].clear()
    assert len((await restored.read(actor))["reviews"]) == 4


async def test_governance_document_budget_rolls_back(monkeypatch):
    from app.storage.metric_governance import GovernanceCapacityExceeded

    monkeypatch.setattr("app.storage.metric_governance.MAX_DOCUMENT_BYTES", 100)
    sessions = MemorySessions()
    store = MetricGovernanceStore(sessions)
    actor = Principal("budget", "engineer", Scope())
    with pytest.raises(GovernanceCapacityExceeded):
        async with store.transaction(actor) as document:
            document["reviews"]["oversize"] = "x" * 200
    assert (await store.read(actor))["reviews"] == {}


async def test_concurrent_review_conflicts_without_lost_updates(service):
    sessions = MemorySessions()
    actor = Principal("a", "engineer", Scope())
    sid = (await sessions.create(actor, "review", "UTC"))["session_id"]
    service.settings.text_to_sql_enabled = True
    result = await service.analyze(QUESTION)
    rid = result["request_id"]
    qid = result["evidence"]["generated_sql"]["queries"][0]["query_id"]
    await sessions.start_request(rid, sid, actor, QUESTION, "Asia/Shanghai")
    await sessions.finish_request(rid, result)
    manager = MetricReviewService(sessions, service.query_service, service.settings)
    results = await asyncio.gather(
        *(
            manager.review(actor, rid, qid, QueryReviewInput(verdict=v, expected_revision=0))
            for v in ("approved", "changes_requested")
        ),
        return_exceptions=True,
    )
    assert sum(isinstance(r, dict) for r in results) == 1
    assert any(isinstance(r, (HTTPException, SessionBusy)) for r in results)
    assert (await manager.get_review(actor, rid, qid))["revision"] == 1


def test_contract_strips_only_request_conjunctions_and_freezes_classification(service, scope):
    sql = "SELECT alarm_type, COUNT(*) AS total FROM v_alarm_events WHERE hostname=:device_0 AND occurred_at>=:start AND occurred_at<:end AND severity=:severity GROUP BY alarm_type"
    query_service = GeneratedSqlService(service.query_service)
    prepared = query_service.prepare(
        GeneratedSqlDraft(disposition="query", sql=sql, severity="critical"),
        "查询 R2 昨天按告警类型统计严重告警数量",
        NOW,
        "UTC",
    )
    query = query_service.execute(prepared, scope).queries[0]
    contract = compile_contract(query, 200)
    assert contract["fixed_filters"] == {"severity": "critical"}
    assert "WHERE" not in contract["sql"]
    assert contract["parameters"] == {}
    assert query.business_limit is None and query.row_budget == 200
    assert "LIMIT" not in contract["sql"]
    altered = deepcopy(query)
    altered.sql = altered.sql.replace("hostname = :device_0 AND", "hostname = :device_0 OR")
    with pytest.raises(SqlRejected):
        compile_contract(altered, 200)


def test_contract_preserves_business_limit_but_not_backend_row_cap(service, scope):
    service.settings.sql_max_rows = 200
    generated = GeneratedSqlService(service.query_service)
    base = "SELECT hostname, interface_name, AVG(packet_loss_pct) AS average_value FROM v_interface_metrics GROUP BY hostname, interface_name ORDER BY average_value DESC"
    for limit in (None, 3, 500):
        draft = GeneratedSqlDraft(
            disposition="query", sql=base + (f" LIMIT {limit}" if limit else "")
        )
        query = generated.execute(generated.prepare(draft, QUESTION, NOW, "UTC"), scope).queries[0]
        assert query.business_limit == limit
        contract = compile_contract(query, 50)  # publication after changing runtime budget
        assert contract["business_limit"] == limit
        assert (f"LIMIT {limit}" in contract["sql"]) if limit else ("LIMIT" not in contract["sql"])
    legacy = query.model_copy(update={"row_budget": None})
    with pytest.raises(SqlRejected):
        compile_contract(legacy, 200)


@pytest.mark.mysql
async def test_actual_mysql_executes_a_published_definition(mysql_service):
    sessions = MemorySessions()
    actor = Principal("review-mysql-test", "engineer", Scope())
    sid = (await sessions.create(actor, "reviewed metric", "Asia/Shanghai"))["session_id"]
    mysql_service.settings.text_to_sql_enabled = True
    response = await mysql_service.analyze(QUESTION)
    assert response["status"] == "partial", response
    rid = response["request_id"]
    qid = response["evidence"]["generated_sql"]["queries"][0]["query_id"]
    await sessions.start_request(rid, sid, actor, QUESTION)
    await sessions.finish_request(rid, response)
    manager = MetricReviewService(sessions, mysql_service.query_service, mysql_service.settings)
    await manager.review(actor, rid, qid, QueryReviewInput(verdict="approved", expected_revision=0))
    await manager.publish(
        actor,
        rid,
        qid,
        PublishMetricInput(
            label="接口丢包排名",
            aliases=[],
            description="按接口计算采样等权均值，降序返回前三个接口。",
            review_revision=1,
            confirm_contract=True,
        ),
    )
    plan = await manager.resolve_named(actor, "查询指标「接口丢包排名」 R2 昨天", "Asia/Shanghai")
    result = await manager.execute(actor, plan.reviewed_metric_plan)
    assert result.status == "ok"
    assert result.queries[0].rows[0]["average_value"] == pytest.approx(6.06)
    assert result.queries[0].data_source == "mysql:authorized-views"
    assert result.queries[0].verification_status == "human_reviewed"


@pytest.mark.parametrize(
    "values",
    [
        {"verdict": "auto_approved", "expected_revision": 0},
        {"verdict": "approved", "expected_revision": -1},
        {"label": "x", "description": "short", "review_revision": 1, "confirm_contract": True},
    ],
)
def test_review_schema_is_closed(values):
    with pytest.raises(ValidationError):
        (QueryReviewInput if "verdict" in values else PublishMetricInput).model_validate(values)
