from datetime import UTC, datetime

import pytest

from app.schemas.models import QueryPlan, Scope
from app.security.sql_guard import scoped_mysql_sql, validate_sql


@pytest.mark.parametrize("metric", ["interface_status", "link_status", "incident_summaries"])
def test_extended_query_views(service, scope, metric):
    plan = QueryPlan(
        devices=["R2"],
        metrics=[metric],
        start_utc=datetime(2026, 10, 10, tzinfo=UTC),
        end_utc=datetime(2026, 10, 11, tzinfo=UTC),
    )
    result = service.query_service.query(plan, scope, "UTC")
    assert result.status == "ok"
    assert result.queries[0].rows
    assert "root_cause" not in result.queries[0].columns


def test_link_peer_acl_is_mandatory(service):
    sql = "SELECT hostname, peer_hostname FROM v_link_status"
    assert not service.query_service.execute(sql, {}, Scope(device_ids=(2,))).rows
    assert service.query_service.execute(sql, {}, Scope(device_ids=(1, 2))).rows == [
        {"hostname": "R2", "peer_hostname": "R1"}
    ]
    secured, parameters = scoped_mysql_sql(validate_sql(sql), Scope(device_ids=(2,)))
    assert "peer_tenant_id = :acl_tenant" in secured
    assert "peer_device_id IN (:acl_device_0)" in secured


@pytest.mark.parametrize(
    "question", ["查询 R2 接口状态", "查询 R2 链路状态", "查询 R2 昨天的故障记录"]
)
async def test_extended_reports_not_raw_sql_only(service, question):
    result = await service.analyze(question)
    assert result["status"] == "completed"
    assert result["report"]["facts"]


def test_extended_live_mysql(mysql_service):
    for metric in ("interface_status", "link_status", "incident_summaries"):
        plan = QueryPlan(
            devices=["R2"],
            metrics=[metric],
            start_utc=datetime(2026, 10, 10, tzinfo=UTC),
            end_utc=datetime(2026, 10, 11, tzinfo=UTC),
        )
        result = mysql_service.query_service.query(plan, Scope(), "UTC")
        assert result.status == "ok" and result.queries[0].rows


def test_link_interface_filter_without_device(service, scope):
    result = service.query_service.query(
        QueryPlan(metrics=["link_status"], interface="eth1"), scope, "UTC"
    )
    assert result.status == "ok"
    assert all(
        row["interface_name"] == "eth1" or row["peer_interface_name"] == "eth1"
        for row in result.queries[0].rows
    )


async def test_short_device_status_question(service):
    result = await service.analyze("查询 R2 状态")
    assert result["status"] == "completed"
    assert result["evidence"]["sql"]["queries"][0]["metric"] == "device_status"
