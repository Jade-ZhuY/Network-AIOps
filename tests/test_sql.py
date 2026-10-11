from datetime import UTC, datetime

import pytest

from app.schemas.models import QueryPlan, Scope
from app.security.sql_guard import SqlRejected, scoped_mysql_sql, validate_sql
from app.storage.fixtures import demo_records
from app.storage.models import VIEW_COLUMNS, Base


def plan(**kwargs):
    return QueryPlan(
        devices=["R2"],
        start_utc=datetime(2026, 10, 10, tzinfo=UTC),
        end_utc=datetime(2026, 10, 11, tzinfo=UTC),
        metrics=["alarm_count", "packet_loss_pct"],
        **kwargs,
    )


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM v_alarm_events",
        "DROP TABLE network_devices",
        "SELECT hostname FROM v_device_status; SELECT hostname FROM v_device_status",
        "SELECT password FROM mysql.user",
        "SELECT root_cause FROM network_incidents",
        "SELECT root_cause FROM v_incident_summaries",
        "SELECT management_ip FROM v_device_status",
        "SELECT hostname FROM other_db.v_device_status",
        "SELECT SLEEP(5) FROM v_device_status",
        "SELECT LOAD_FILE('/etc/passwd') FROM v_device_status",
        "SELECT BENCHMARK(1000000, 1) FROM v_device_status",
        "SELECT hostname INTO OUTFILE '/tmp/data' FROM v_device_status",
        "SELECT hostname FROM v_device_status FOR UPDATE",
        "SELECT hostname FROM v_device_status UNION SELECT hostname FROM v_device_status",
        "SELECT * FROM v_device_status",
        "SELECT @@version FROM v_device_status",
        "SELECT hostname FROM v_device_status WHERE device_id IN (SELECT device_id FROM network_devices)",
        "WITH t AS (SELECT hostname FROM v_device_status) SELECT hostname FROM t",
        "SELECT a.hostname FROM v_device_status a CROSS JOIN v_device_status b",
        "SELECT hostname FROM v_device_status LIMIT -1",
        "SELECT hostname FROM v_device_status LIMIT :limit",
        "SELECT hostname AS tenant_id, tenant_id FROM v_device_status",
        "SELECT hostname FROM v_device_status WHERE hostname=:acl_tenant",
        "SELECT hostname FROM v_device_status /*! UNION SELECT hostname FROM network_devices */",
        "SELECT /*+ MAX_EXECUTION_TIME(0) */ hostname FROM v_device_status",
    ],
)
def test_dangerous_sql_rejected(sql):
    with pytest.raises(SqlRejected):
        validate_sql(sql)


def test_safe_aggregate_and_limit():
    ast = validate_sql(
        "SELECT hostname, AVG(packet_loss_pct) AS value FROM v_interface_metrics GROUP BY hostname ORDER BY value LIMIT 9999",
        2,
    )
    assert ast.args["limit"].expression.this == "3"


def test_seed_model_and_no_label_leak():
    assert len(Base.metadata.tables) == 6
    records = demo_records()
    assert {row["incident_id"] for row in records["network_incidents"]} == {
        "INC-BGP-001",
        "INC-OSPF-002",
        "INC-TRAFFIC-003",
    }
    assert all(row["root_cause"] is None for row in records["network_incidents"])
    assert all("root_cause" not in columns for columns in VIEW_COLUMNS.values())


def test_expected_fixture_aggregates(service, scope):
    result = service.query_service.query(plan(), scope, "UTC")
    assert result.status == "ok"
    assert result.queries[0].rows[0]["alarm_count"] == 3
    assert result.queries[1].rows[0]["average_value"] == pytest.approx(6.06)
    assert result.queries[1].unit == "%"


def test_half_open_window_and_zero_not_fabricated(service, scope):
    query_plan = QueryPlan(
        devices=["R2"],
        start_utc=datetime(2026, 10, 10, 6, tzinfo=UTC),
        end_utc=datetime(2026, 10, 10, 6, 15, tzinfo=UTC),
        metrics=["alarm_count"],
    )
    result = service.query_service.query(query_plan, scope, "UTC")
    assert result.queries[0].rows[0]["alarm_count"] == 1
    query_plan.start_utc = datetime(2030, 1, 1, tzinfo=UTC)
    query_plan.end_utc = datetime(2030, 1, 2, tzinfo=UTC)
    result = service.query_service.query(query_plan, scope, "UTC")
    assert result.status == "no_data"
    assert all(not query.rows for query in result.queries)


def test_scope_is_enforced_even_without_predicates(service):
    sql = "SELECT hostname FROM v_device_status WHERE 1=1 OR hostname='R99'"
    result = service.query_service.execute(sql, {}, Scope(device_ids=(2,)))
    assert result.rows == [{"hostname": "R2"}]
    result = service.query_service.execute(
        "SELECT hostname FROM v_device_status",
        {},
        Scope(tenant_id="other-tenant", device_ids=(99,)),
    )
    assert result.rows == [{"hostname": "R99"}]
    result = service.query_service.execute(
        "SELECT hostname FROM v_device_status", {}, Scope(device_ids=())
    )
    assert not result.rows


def test_mysql_scope_wraps_every_join():
    sql = "SELECT a.hostname, COUNT(*) AS count FROM v_alarm_events a JOIN v_device_status d ON a.device_id=d.device_id GROUP BY a.hostname"
    secured, bindings = scoped_mysql_sql(validate_sql(sql), Scope(device_ids=(2,)))
    assert secured.count("tenant_id = :acl_tenant") == 2
    assert secured.count("device_id IN (:acl_device_0)") == 2
    assert bindings == {"acl_tenant": "demo-tenant", "acl_device_0": 2}


def test_unauthorized_device_and_mutation(service, scope):
    query_plan = plan()
    query_plan.devices = ["R99"]
    assert service.query_service.query(query_plan, scope, "UTC").status == "forbidden"
    assert (
        service.query_service.query(plan(), scope, "UTC", "删除所有告警数据").status == "forbidden"
    )


def test_row_cap(service, scope):
    service.query_service.settings.sql_max_rows = 2
    result = service.query_service.execute(
        "SELECT alarm_id FROM v_alarm_events ORDER BY alarm_id", {}, scope
    )
    assert len(result.rows) == 2
    assert result.truncated


def test_database_timeout_is_explicit(service, scope, monkeypatch):
    def timed_out(*args):
        raise TimeoutError

    monkeypatch.setattr(service.backend, "read", timed_out)
    assert service.query_service.query(plan(), scope, "UTC").status == "timeout"


def test_sqlite_progress_handler_interrupts_real_execution(service, scope, monkeypatch):
    import itertools

    from sqlalchemy.exc import DBAPIError

    ticks = itertools.chain([0.0], itertools.repeat(100.0))
    monkeypatch.setattr("app.storage.backends.time.monotonic", lambda: next(ticks))
    with pytest.raises(DBAPIError, match="interrupted"):
        service.query_service.execute(
            "SELECT COUNT(*) AS count FROM v_interface_metrics", {}, scope
        )
