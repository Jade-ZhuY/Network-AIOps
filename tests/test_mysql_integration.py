from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.schemas.models import QueryPlan, Scope
from scripts.demo import QUESTIONS

pytestmark = pytest.mark.mysql


def test_live_mysql_expected_rows_and_readonly_grants(mysql_service):
    plan = QueryPlan(
        devices=["R2"],
        start_utc=datetime(2026, 10, 10, tzinfo=UTC),
        end_utc=datetime(2026, 10, 11, tzinfo=UTC),
        metrics=["alarm_count", "packet_loss_pct"],
    )
    result = mysql_service.query_service.query(plan, Scope(), "UTC")
    assert result.status == "ok"
    assert result.queries[0].rows[0]["alarm_count"] == 3
    assert result.queries[1].rows[0]["average_value"] == pytest.approx(6.06)
    assert all(query.data_source == "mysql:authorized-views" for query in result.queries)
    with mysql_service.backend.engine.connect() as connection:
        grants = " ".join(
            str(row[0]) for row in connection.exec_driver_sql("SHOW GRANTS FOR CURRENT_USER()")
        )
        assert "GRANT SELECT" in grants
        assert "ALL PRIVILEGES" not in grants
        assert "INSERT" not in grants
        with pytest.raises(DBAPIError):
            connection.execute(text("SELECT root_cause FROM network_incidents"))
        connection.rollback()
        with pytest.raises(DBAPIError):
            # WHERE 1=0 avoids record mutation even if misconfigured; grants above
            # are independently checked before this database privilege probe.
            connection.execute(text("DELETE FROM network_alarms WHERE 1=0"))
        connection.rollback()


def test_live_mysql_acl_or_predicate_and_other_tenant(mysql_service):
    result = mysql_service.query_service.execute(
        "SELECT hostname FROM v_device_status WHERE 1=1 OR hostname='R99'",
        {},
        Scope(device_ids=(2,)),
    )
    assert result.rows == [{"hostname": "R2"}]
    other = mysql_service.query_service.execute(
        "SELECT hostname FROM v_device_status",
        {},
        Scope(tenant_id="other-tenant", device_ids=(99,)),
    )
    assert other.rows == [{"hostname": "R99"}]
    empty = mysql_service.query_service.execute(
        "SELECT hostname FROM v_device_status", {}, Scope(device_ids=())
    )
    assert not empty.rows


def test_live_mysql_unauthorized_name_forbidden(mysql_service):
    plan = QueryPlan(devices=["R99"], metrics=["device_status"])
    assert mysql_service.query_service.query(plan, Scope(), "UTC").status == "forbidden"


@pytest.mark.parametrize("question", QUESTIONS)
async def test_live_mysql_all_demo_cases(mysql_service, question):
    result = await mysql_service.analyze(question)
    assert result["status"] == "completed"
    assert result["report_calls"] == 1
    assert result["persistence_enabled"] is False
    if result["evidence"]["sql"]:
        assert result["evidence"]["sql"]["status"] == "ok"
        assert result["report"]["facts"]


async def test_live_mysql_no_data_and_failure_disclosed(mysql_service):
    result = await mysql_service.analyze("查询 R2 2030-01-01 的平均丢包率")
    assert result["status"] == "no_evidence"
    assert not result["report"]["facts"]
    assert result["evidence"]["sql"]["status"] == "no_data"


def test_live_mysql_limit(mysql_service):
    mysql_service.settings.sql_max_rows = 2
    result = mysql_service.query_service.execute(
        "SELECT alarm_id FROM v_alarm_events ORDER BY alarm_id", {}, Scope()
    )
    assert len(result.rows) == 2
    assert result.truncated
