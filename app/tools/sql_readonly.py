import re
import time
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.exc import DBAPIError

from app.schemas.models import QueryEvidence, QueryPlan, Scope, SqlResult
from app.security.redaction import redact_sensitive_text
from app.security.sql_guard import SqlRejected, validate_sql
from app.storage.models import VIEW_COLUMNS
from app.tools.metric_catalog import CATALOG


def utc_sql(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S.%f")


def json_value(value):
    if isinstance(value, datetime):
        return value.replace(tzinfo=UTC).isoformat()
    if isinstance(value, str):
        return redact_sensitive_text(value)
    return value


class QueryService:
    def __init__(self, backend, settings):
        self.backend = backend
        self.settings = settings

    def schema(self):
        return {
            "views": VIEW_COLUMNS,
            "metrics": CATALOG,
            "time_storage": "UTC",
            "dialect": "single SELECT, explicit columns, limited aggregate functions; no CTE/subquery",
        }

    def execute(self, sql: str, parameters: dict, scope: Scope):
        ast = validate_sql(sql, self.settings.sql_max_rows)
        return self.backend.read(ast, parameters, scope)

    def query(self, plan: QueryPlan, scope: Scope, timezone: str, question: str = "") -> SqlResult:
        window = [plan.start_utc.isoformat(), plan.end_utc.isoformat()] if plan.start_utc else []
        # Natural-language mutation requests never become a successful SELECT.
        if re.search(
            r"删除|修改|清空|重置|系统账号|密码|drop\b|delete\b|truncate\b|update\b|insert\b|;\s*select|--|/\*|\bor\s+1\s*=\s*1",
            question,
            re.I,
        ):
            return SqlResult(
                status="forbidden",
                time_range_utc=window,
                timezone=timezone,
                warnings=["请求超出只读网络指标查询范围"],
            )
        snapshots = ("device_status", "interface_status", "link_status")
        if any(metric not in snapshots for metric in plan.metrics) and not plan.start_utc:
            return SqlResult(
                status="error", timezone=timezone, missing_evidence=["查询缺少时间范围"]
            )
        evidence = []
        total_deadline = time.monotonic() + self.settings.sql_timeout_ms / 1000
        try:
            if plan.devices:
                authorized = self.execute("SELECT hostname FROM v_device_status", {}, scope)
                if not set(plan.devices).issubset({row["hostname"] for row in authorized.rows}):
                    return SqlResult(
                        status="forbidden",
                        timezone=timezone,
                        time_range_utc=window,
                        warnings=["设备不在服务端授权范围内"],
                    )
            for metric in dict.fromkeys(plan.metrics):
                if time.monotonic() > total_deadline:
                    raise TimeoutError
                sql, parameters = self.build_query(metric, plan)
                result = self.execute(sql, parameters, scope)
                meaningful = [row for row in result.rows if row.get("sample_count", 1) != 0]
                evidence.append(
                    QueryEvidence(
                        query_id=f"query_{uuid4().hex}",
                        metric=metric,
                        sql=validate_sql(sql, self.settings.sql_max_rows).sql(dialect="mysql"),
                        parameters=parameters,
                        columns=result.columns,
                        rows=[{k: json_value(v) for k, v in row.items()} for row in meaningful],
                        row_count=len(meaningful),
                        truncated=result.truncated,
                        unit=CATALOG[metric]["unit"],
                        description=CATALOG[metric]["description"],
                        data_source=self.backend.source,
                        data_freshness_utc=max(
                            (
                                str(
                                    row.get("latest_sample")
                                    or row.get("occurred_at")
                                    or row.get("started_at")
                                    or ""
                                )
                                for row in meaningful
                            ),
                            default="",
                        )
                        or None,
                    )
                )
        except (TimeoutError, DBAPIError) as exc:
            is_timeout = isinstance(exc, TimeoutError) or any(
                word in str(getattr(exc, "orig", "")).lower()
                for word in ("interrupted", "timeout", "3024", "1317")
            )
            return SqlResult(
                status="timeout" if is_timeout else "error",
                queries=evidence,
                time_range_utc=window,
                timezone=timezone,
                missing_evidence=[
                    "只读查询超时" if is_timeout else "数据库查询失败（已隐藏连接信息）"
                ],
            )
        except (SqlRejected, PermissionError):
            return SqlResult(
                status="forbidden",
                time_range_utc=window,
                timezone=timezone,
                warnings=["查询被工具安全策略阻断"],
            )
        status = "ok" if any(item.rows for item in evidence) else "no_data"
        warnings = (
            ["演示数据，非真实采集；固定基准日期 2026-10-10"]
            if self.backend.source.startswith("mock")
            else []
        )
        if any(item.truncated for item in evidence):
            warnings.append("结果达到行数上限，表格仅包含部分记录")
        if any(metric in snapshots for metric in plan.metrics):
            warnings.append("状态快照未提供采集时间，不等同于实时或查询窗口内的历史观测。")
        return SqlResult(
            status=status,
            queries=evidence,
            time_range_utc=window,
            timezone=timezone,
            warnings=warnings,
            missing_evidence=["时间范围内没有匹配的数据，空结果不表示指标为零"]
            if status == "no_data"
            else [],
        )

    @staticmethod
    def build_query(metric, plan: QueryPlan):
        parameters = {}
        where = []
        if plan.devices:
            for i, device in enumerate(plan.devices):
                parameters[f"device_{i}"] = device
            where.append(
                "hostname IN (" + ", ".join(f":device_{i}" for i in range(len(plan.devices))) + ")"
            )
        if metric == "device_status":
            sql = "SELECT device_id, hostname, region, status FROM v_device_status"
        elif metric == "interface_status":
            sql = (
                "SELECT hostname, interface_name, admin_status, oper_status FROM v_interface_status"
            )
            if plan.interface:
                parameters["interface"] = plan.interface
                where.append("interface_name=:interface")
        elif metric == "link_status":
            sql = "SELECT link_id, hostname, interface_name, peer_hostname, peer_interface_name, link_status FROM v_link_status"
            if where:
                device_predicate = where.pop()
                peer_predicate = device_predicate.replace("hostname", "peer_hostname")
                if plan.interface:
                    parameters["interface"] = plan.interface
                    where.append(
                        f"(({device_predicate} AND interface_name=:interface) OR ({peer_predicate} AND peer_interface_name=:interface))"
                    )
                else:
                    where.append(f"({device_predicate} OR {peer_predicate})")
            elif plan.interface:
                parameters["interface"] = plan.interface
                where.append("(interface_name=:interface OR peer_interface_name=:interface)")
        elif metric == "incident_summaries":
            sql = "SELECT incident_id, hostname, started_at, ended_at, symptom FROM v_incident_summaries"
            parameters.update(start=utc_sql(plan.start_utc), end=utc_sql(plan.end_utc))
            where.extend(["started_at>=:start", "started_at<:end"])
        else:
            time_column = "occurred_at" if metric.startswith("alarm") else "sample_time"
            parameters.update(start=utc_sql(plan.start_utc), end=utc_sql(plan.end_utc))
            where.extend([f"{time_column} >= :start", f"{time_column} < :end"])
            if metric.startswith("alarm"):
                if plan.severity:
                    where.append("severity = :severity")
                    parameters["severity"] = plan.severity
                if plan.alarm_type:
                    where.append("alarm_type = :alarm_type")
                    parameters["alarm_type"] = plan.alarm_type
                sql = (
                    "SELECT hostname, COUNT(*) AS alarm_count, MAX(occurred_at) AS latest_sample FROM v_alarm_events"
                    if metric == "alarm_count"
                    else "SELECT alarm_id, hostname, severity, alarm_type, description, occurred_at FROM v_alarm_events"
                )
            else:
                if plan.interface:
                    where.append("interface_name = :interface")
                    parameters["interface"] = plan.interface
                # metric identifier comes only from the Pydantic enum + catalog.
                if metric not in CATALOG:
                    raise SqlRejected("Unknown metric")
                sql = f"SELECT hostname, interface_name, AVG({metric}) AS average_value, MIN({metric}) AS min_value, MAX({metric}) AS max_value, COUNT({metric}) AS sample_count, MAX(sample_time) AS latest_sample FROM v_interface_metrics"
        if where:
            sql += " WHERE " + " AND ".join(where)
        if metric == "alarm_count":
            sql += " GROUP BY hostname ORDER BY hostname"
        elif metric == "alarm_events":
            sql += " ORDER BY occurred_at, alarm_id"
        elif metric not in (
            "device_status",
            "interface_status",
            "link_status",
            "incident_summaries",
        ):
            sql += " GROUP BY hostname, interface_name ORDER BY hostname, interface_name"
        elif metric == "incident_summaries":
            sql += " ORDER BY started_at, incident_id"
        elif metric == "link_status":
            sql += " ORDER BY link_id"
        else:
            sql += " ORDER BY hostname"
        return sql, parameters
