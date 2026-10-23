from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.governance.feedback import capture_in_document, classify, signature
from app.main import create_app
from app.schemas.models import Scope, SqlResult
from app.security.auth import Principal, current_principal
from app.storage.metric_governance import GovernanceStorageUnavailable
from tests.test_metric_review import (
    HEADERS,
    QUESTION,
    actor_dependency,
    approve,
    named_query,
    publish,
    source_query,
)


@pytest.fixture
def fixture_app():
    app = create_app(
        Settings(
            _env_file=None,
            persistence_backend="memory",
            llm_mode="mock",
            data_backend="mock",
            embedding_mode="mock",
            text_to_sql_enabled=True,
            api_auth_token="engineer-review-token",
            api_admin_token="admin-review-token",
            enable_demo_api=False,
        )
    )
    with TestClient(app) as client:
        yield app, client


def chat(client, question, timezone="Asia/Shanghai"):
    sid = client.post("/api/v1/sessions", headers=HEADERS, json={}).json()["session_id"]
    response = client.post(
        "/api/v1/chat",
        headers=HEADERS,
        json={"session_id": sid, "message": question, "timezone": timezone},
    )
    assert response.status_code == 200, response.text
    return response.json()


def list_cases(client, query=""):
    response = client.get("/api/v1/governance/cases" + query, headers=HEADERS)
    assert response.status_code == 200, response.text
    return response.json()


def case_detail(client, cid):
    response = client.get("/api/v1/governance/cases/" + cid, headers=HEADERS)
    assert response.status_code == 200, response.text
    return response.json()


def verify(client, cid, proof, metric=None, **extra):
    row = case_detail(client, cid)
    return client.post(
        f"/api/v1/governance/cases/{cid}/verify",
        headers=HEADERS,
        json={
            "expected_revision": row["revision"],
            "proof_request_id": proof,
            "resolution_kind": "published_metric" if metric else "original_query_fixed",
            "metric_id": metric,
            "note": "已重新取数并核对该问题的查询定义与证据。",
            "confirm_scope": True,
            **extra,
        },
    )


def published_case(client):
    response, _, path = source_query(client)
    cid = response["governance_feedback"]["case_ids"][0]
    approve(client, path)
    metric = publish(client, path).json()
    proof = named_query(client, response["session_id"])
    return cid, response, path, metric, proof


def test_source_gap_is_automatically_collected_and_conservatively_deduplicated(fixture_app):
    _, client = fixture_app
    first = chat(client, "查询 R2 昨天 CPU 温度")
    assert first["governance_feedback"]["capture_status"] == "recorded"
    cid = first["governance_feedback"]["case_ids"][0]
    row = case_detail(client, cid)
    assert row["kind"] == "source_missing" and row["status"] == "open"
    revision = row["revision"]
    for _ in range(2):
        assert (
            client.post(
                "/api/v1/governance/capture/" + first["request_id"], headers=HEADERS
            ).status_code
            == 200
        )
    assert case_detail(client, cid)["revision"] == revision
    second = chat(client, "查询 R2 昨天 CPU 温度")
    assert second["governance_feedback"]["case_ids"] == [cid]
    assert list_cases(client)["cases"][0]["occurrence_count"] == 2
    chat(client, "查询 R3 昨天 CPU 温度")
    chat(client, "查询 R2 2026-10-01 CPU 温度")
    assert list_cases(client)["total"] == 3
    assert signature("R 2", "UTC") != signature("R2", "UTC")


@pytest.mark.parametrize(
    "question",
    [
        "查询 R2 昨天丢包率",
        "查询 R2 的丢包率",
        "查询 R99 昨天告警",
        "查询 R2 2030-01-01 按平均丢包率排名前3的接口",
        "删除所有告警数据",
        "OSPF 是什么？",
    ],
)
def test_normal_missing_arguments_empty_results_permissions_and_rag_do_not_create_gaps(
    fixture_app, question
):
    _, client = fixture_app
    result = chat(client, question)
    assert result["governance_feedback"]["capture_status"] == "not_needed", result
    assert list_cases(client)["total"] == 0


def test_ambiguity_and_sql_review_have_distinct_categories(fixture_app):
    _, client = fixture_app
    result = chat(client, "查询 R2 昨天设备整体平均丢包率")
    assert result["status"] == "needs_clarification"
    cid = result["governance_feedback"]["case_ids"][0]
    assert case_detail(client, cid)["kind"] == "semantic_ambiguity"
    source_query(client)
    assert {c["kind"] for c in list_cases(client)["cases"]} == {"semantic_ambiguity", "sql_review"}


def test_full_feedback_review_publish_execute_verify_close_and_reopen(fixture_app):
    _, client = fixture_app
    cid, original, path, metric, proof = published_case(client)
    row = case_detail(client, cid)
    assert row["status"] == "open"  # approving/publishing alone is not verified resolution
    assert row["metric_links"][metric["metric_id"]]["active"]
    assert proof["request_id"] in row["occurrences"]
    assert proof["governance_feedback"]["case_ids"] == [cid]
    result = verify(client, cid, proof["request_id"], metric["metric_id"])
    assert result.status_code == 200, result.text
    receipt = result.json()
    assert receipt["verified"] and receipt["case"]["status"] == "resolved", receipt
    assert all(check["passed"] for check in receipt["checks"])
    assert list_cases(client)["counts"]["resolved"] == 1
    # No SQL or numeric business rows are copied into the issue store.
    assert "rows" not in str(receipt["case"])
    assert "SELECT" not in str(receipt["case"])
    changed = client.put(
        path + "/review",
        headers=HEADERS,
        json={
            "verdict": "changes_requested",
            "comment": "统计口径发现问题，先撤回后修复",
            "expected_revision": 1,
        },
    )
    assert changed.status_code == 200
    reopened = case_detail(client, cid)
    assert reopened["status"] == "open" and reopened["resolution"] is None
    assert not reopened["metric_links"][metric["metric_id"]]["active"]
    old = verify(client, cid, proof["request_id"], metric["metric_id"]).json()
    assert not old["verified"]
    approve(client, path, 2)
    newer = publish(client, path, review_revision=3).json()
    assert newer["version"] == 2
    old = verify(client, cid, proof["request_id"], metric["metric_id"]).json()
    assert not old["verified"]
    current_proof = named_query(client, original["session_id"])
    assert verify(client, cid, current_proof["request_id"], metric["metric_id"]).json()["verified"]


def test_unverified_original_or_unrelated_metric_is_not_a_proof(fixture_app):
    _, client = fixture_app
    original, _, path = source_query(client)
    cid = original["governance_feedback"]["case_ids"][0]
    failed = verify(client, cid, original["request_id"]).json()
    assert not failed["verified"] and failed["case"]["status"] == "open"
    assert any(not c["passed"] for c in failed["checks"])
    other, _, other_path = source_query(client, "查询 R2 昨天按告警类型统计数量")
    approve(client, other_path)
    unrelated = publish(client, other_path, label="告警类型统计", aliases=[]).json()
    proof = named_query(client, other["session_id"], "查询指标「告警类型统计」 R2 昨天")
    failed = verify(client, cid, proof["request_id"], unrelated["metric_id"]).json()
    assert not failed["verified"]
    assert next(c for c in failed["checks"] if c["code"] == "related_metric")["passed"] is False
    assert case_detail(client, cid)["last_verification"]["verified"] is False


def test_processing_notes_cas_filters_pagination_and_no_manual_resolved_state(fixture_app):
    _, client = fixture_app
    original = chat(client, "查询 R2 昨天 CPU 温度")
    cid = original["governance_feedback"]["case_ids"][0]
    row = case_detail(client, cid)
    body = {
        "status": "in_progress",
        "assignee": "数据维护人",
        "note": "需要新增对应采集字段与指标定义",
        "expected_revision": row["revision"],
    }
    response = client.patch(f"/api/v1/governance/cases/{cid}", headers=HEADERS, json=body)
    assert response.status_code == 200
    assert response.json()["assignee"] == "数据维护人"
    assert (
        client.patch(f"/api/v1/governance/cases/{cid}", headers=HEADERS, json=body).status_code
        == 409
    )
    assert (
        client.patch(
            f"/api/v1/governance/cases/{cid}", headers=HEADERS, json={**body, "status": "resolved"}
        ).status_code
        == 422
    )
    assert (
        client.patch(
            f"/api/v1/governance/cases/{cid}", headers=HEADERS, json={**body, "sql": "SELECT 1"}
        ).status_code
        == 422
    )
    filtered = list_cases(client, "?status=in_progress&kind=source_missing&limit=1")
    assert filtered["total"] == 1 and filtered["counts"]["in_progress"] == 1
    assert list_cases(client, "?offset=1&limit=1")["cases"] == []
    assert client.get("/api/v1/governance/cases?limit=1000", headers=HEADERS).status_code == 422
    assert client.get("/api/v1/governance/cases?status=fake", headers=HEADERS).status_code == 422


def test_dismissed_is_not_resolved_and_new_occurrence_reopens(fixture_app):
    _, client = fixture_app
    original = chat(client, "查询 R2 昨天 CPU 温度")
    cid = original["governance_feedback"]["case_ids"][0]
    row = case_detail(client, cid)
    result = client.patch(
        f"/api/v1/governance/cases/{cid}",
        headers=HEADERS,
        json={
            "status": "dismissed",
            "note": "本期暂不接入该指标采集",
            "expected_revision": row["revision"],
        },
    )
    assert result.status_code == 200
    assert list_cases(client)["counts"]["resolved"] == 0
    chat(client, "查询 R2 昨天 CPU 温度")
    assert case_detail(client, cid)["status"] == "open"


def test_old_success_cannot_hide_a_later_regression_and_withdrawal_reopens(fixture_app):
    _, client = fixture_app
    cid, _, _, metric, proof = published_case(client)
    assert verify(client, cid, proof["request_id"], metric["metric_id"]).json()["verified"]
    chat(client, QUESTION)  # same natural wording still needs model SQL, so reopen honestly
    failed = verify(client, cid, proof["request_id"], metric["metric_id"]).json()
    assert not failed["verified"]
    assert not next(c for c in failed["checks"] if c["code"] == "fresh_proof")["passed"]
    replay = client.post(f"/api/v1/sessions/{proof['session_id']}/resume", headers=HEADERS)
    assert replay.status_code == 200
    assert replay.json()["request_id"] == proof["request_id"]
    failed = verify(client, cid, proof["request_id"], metric["metric_id"]).json()
    assert not failed["verified"]
    assert not next(c for c in failed["checks"] if c["code"] == "actual_execution_time")["passed"]
    fresh = named_query(client, proof["session_id"])
    assert verify(client, cid, fresh["request_id"], metric["metric_id"]).json()["verified"]
    assert (
        client.delete(
            f"/api/v1/metrics/reviewed/{metric['metric_id']}?version=1", headers=HEADERS
        ).status_code
        == 200
    )
    assert case_detail(client, cid)["status"] == "open"


def test_original_problem_retries_after_execution_repair_can_verify_first_layer(
    fixture_app, monkeypatch
):
    app, client = fixture_app
    real_sql = app.state.service.runtime.sql

    async def fail(*args, **kwargs):
        return SqlResult(status="error", missing_evidence=["查询组件暂时未就绪"])

    monkeypatch.setattr(app.state.service.runtime, "sql", fail)
    original = chat(client, "查询 R2 昨天丢包率")
    cid = original["governance_feedback"]["case_ids"][0]
    assert case_detail(client, cid)["kind"] == "execution_failure"
    monkeypatch.setattr(app.state.service.runtime, "sql", real_sql)
    success = chat(client, "查询 R2 昨天丢包率")
    assert success["status"] == "completed"
    result = verify(client, cid, success["request_id"])
    assert result.status_code == 200 and result.json()["verified"], result.text


def test_owner_scope_isolation_and_closed_input(fixture_app):
    app, client = fixture_app
    original = chat(client, "查询 R2 昨天 CPU 温度")
    cid = original["governance_feedback"]["case_ids"][0]
    assert client.get("/api/v1/governance/cases").status_code == 401
    for denied in (
        Principal("other", "engineer", Scope()),
        Principal("netops-engineer", "engineer", Scope(tenant_id="other")),
        Principal("netops-engineer", "engineer", Scope(device_ids=(2,))),
    ):
        app.dependency_overrides[current_principal] = actor_dependency(denied)
        assert list_cases(client)["total"] == 0
        assert client.get(f"/api/v1/governance/cases/{cid}", headers=HEADERS).status_code == 404
        assert (
            client.post(
                "/api/v1/governance/capture/" + original["request_id"], headers=HEADERS
            ).status_code
            == 404
        )
    app.dependency_overrides.clear()
    result = verify(client, cid, original["request_id"], confirm_scope=1)
    assert result.status_code == 422
    assert client.post("/api/v1/governance/collect?limit=1000", headers=HEADERS).status_code == 422


def test_pending_capture_is_explicit_saved_request_can_be_backfilled(fixture_app, monkeypatch):
    app, client = fixture_app
    monkeypatch.setattr("app.governance.feedback.MAX_CASES", 0)
    original = chat(client, "查询 R2 昨天 CPU 温度")
    assert original["status"] == "not_matched" and original["checkpoint_saved"]
    assert original["governance_feedback"]["capture_status"] == "pending"
    history = client.get("/api/v1/requests/" + original["request_id"], headers=HEADERS).json()
    assert history["response"]["governance_feedback"]["capture_status"] == "pending"
    monkeypatch.setattr("app.governance.feedback.MAX_CASES", 300)
    collected = client.post("/api/v1/governance/collect?limit=20", headers=HEADERS).json()
    assert collected["recorded"] == 1 and not collected["pending"]
    first = list_cases(client)["cases"][0]
    again = client.post("/api/v1/governance/collect?limit=20", headers=HEADERS).json()
    assert again["recorded"] == 1
    assert case_detail(client, first["case_id"])["revision"] == first["revision"]


def test_feedback_store_outage_does_not_claim_saved_feedback_or_lose_business_response(
    fixture_app, monkeypatch
):
    app, client = fixture_app

    async def failed(*args):
        raise GovernanceStorageUnavailable

    monkeypatch.setattr(app.state.service.governance.store, "read", failed)
    result = chat(client, QUESTION)
    assert result["status"] == "partial" and result["checkpoint_saved"]
    assert result["governance_feedback"]["capture_status"] == "pending"
    assert result["governance_feedback"]["reason"] == "storage_unavailable"
    assert client.get("/api/v1/governance/cases", headers=HEADERS).status_code == 503


def test_failed_metric_planning_is_collected_without_provider_error_text(fixture_app, monkeypatch):
    app, client = fixture_app

    async def broken(*args, **kwargs):
        raise RuntimeError("SECRET_PROVIDER_ERROR")

    monkeypatch.setattr(app.state.service.runtime, "plan_request", broken)
    result = chat(client, QUESTION)
    assert result["status"] == "failed"
    assert result["governance_feedback"]["capture_status"] == "recorded"
    row = case_detail(client, result["governance_feedback"]["case_ids"][0])
    assert row["kind"] == "execution_failure"
    assert "SECRET_PROVIDER_ERROR" not in str(row)


def test_semantic_clarification_closes_only_its_saved_same_context_investigation(fixture_app):
    _, client = fixture_app
    first = chat(client, "查询 R2 昨天设备整体平均丢包率")
    cid = first["governance_feedback"]["case_ids"][0]
    proof = client.post(
        "/api/v1/chat",
        headers=HEADERS,
        json={"session_id": first["session_id"], "message": "先算每个接口均值，再按接口等权"},
    ).json()
    assert proof["status"] == "completed", proof
    assert proof["governance_feedback"]["case_ids"] == [cid]
    result = verify(client, cid, proof["request_id"], resolution_kind="clarification_confirmed")
    assert result.status_code == 200 and result.json()["verified"], result.text
    repeated = chat(client, "查询 R2 昨天设备整体平均丢包率")
    assert repeated["status"] == "needs_clarification"
    assert case_detail(client, cid)["status"] == "open"
    wrong = chat(client, "查询 R3 昨天丢包率按接口等权")
    result = verify(client, cid, wrong["request_id"], resolution_kind="clarification_confirmed")
    assert not result.json()["verified"]


def test_capture_does_not_store_raw_rows_or_change_the_source_response():
    request = {
        "request_id": "r1",
        "session_id": "s1",
        "message": "查询 R2 CPU 温度",
        "timezone": "UTC",
        "status": "not_matched",
        "completed_at": "2026-10-20T00:00:00+00:00",
        "response": {
            "route": "sql",
            "status": "not_matched",
            "metric_match": {"status": "miss"},
            "evidence": {
                "generated_sql": {
                    "status": "unavailable",
                    "reason_codes": ["source_data_missing"],
                    "missing_evidence": ["源未提供"],
                }
            },
        },
    }
    before = deepcopy(request)
    document = {"reviews": {}, "metrics": {}}
    first = capture_in_document(document, request, "tester")
    assert first and request == before
    version = document["feedback_cases"][first[0]]["revision"]
    capture_in_document(document, request, "tester")
    assert document["feedback_cases"][first[0]]["revision"] == version
    assert classify({"route": "rag", "status": "failed"}) is None


def test_history_uses_one_governance_snapshot_instead_of_one_large_read_per_message(
    fixture_app, monkeypatch
):
    app, client = fixture_app
    original, _, _ = source_query(client)
    named_query(client, original["session_id"], QUESTION)
    real_read = app.state.service.metric_reviews.store.read
    reads = []

    async def counted(*args):
        reads.append(True)
        return await real_read(*args)

    monkeypatch.setattr(app.state.service.metric_reviews.store, "read", counted)
    result = client.get(f"/api/v1/sessions/{original['session_id']}/messages", headers=HEADERS)
    assert result.status_code == 200 and len(result.json()["messages"]) == 2
    assert len(reads) == 1


@pytest.mark.mysql
def test_full_feedback_http_path_with_actual_readonly_mysql(request):
    if not request.config.getoption("--run-mysql"):
        pytest.skip("Explicit MySQL opt-in required")
    settings = Settings(
        llm_mode="mock",
        data_backend="mysql",
        embedding_mode="mock",
        rag_vector_backend="memory",
        persistence_backend="memory",
        text_to_sql_enabled=True,
        api_auth_token="engineer-review-token",
        enable_demo_api=False,
    )
    with TestClient(create_app(settings)) as client:
        cid, _, _, metric, proof = published_case(client)
        assert (
            proof["evidence"]["reviewed_metric"]["queries"][0]["data_source"]
            == "mysql:authorized-views"
        )
        result = verify(client, cid, proof["request_id"], metric["metric_id"])
        assert result.status_code == 200 and result.json()["verified"], result.text
