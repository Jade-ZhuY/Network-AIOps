"""Execute a model-written SELECT with server-enforced request and ACL boundaries."""

import re
import time
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.exc import DBAPIError
from sqlglot import exp

from app.agents.metric_planning import explicit_devices
from app.agents.planning import MUTATION, resolve_window
from app.schemas.generated_sql import (
    GeneratedSqlEvidence,
    GeneratedSqlResult,
    SqlRequestContext,
)
from app.security.generated_sql_guard import (
    TIME_COLUMNS,
    SqlContextMissing,
    SqlDataUnavailable,
    bound_parameters,
    secure_request_sql,
    validate_generated_sql,
)
from app.security.sql_guard import SqlRejected
from app.semantics.capabilities import UNSUPPORTED_METRICS
from app.semantics.catalog import CATALOG_VERSION, DEFINITIONS
from app.tools.sql_readonly import json_value

BUSINESS_WARNING = (
    "模型生成 SQL；已做结构、白名单和权限检查，但业务口径未经人工验证，请核对后使用。"
)


def preflight_unavailable(question, metric_match=None):
    if MUTATION.search(question):
        return GeneratedSqlResult(
            status="forbidden",
            reason_codes=["read_only_request_guard"],
            warnings=["仅支持只读查询。"],
        )
    if UNSUPPORTED_METRICS.search(question):
        return GeneratedSqlResult(
            status="unavailable",
            reason_codes=["source_data_missing"],
            missing_evidence=[
                "白名单视图没有请求的 CPU/内存/温度/吞吐等指标，生成 SQL 不会补造采集数据。"
            ],
        )
    codes = set(metric_match.reason_codes if metric_match else [])
    if codes & {
        "unsupported_weighting",
        "snapshot_not_history",
        "incident_time_basis",
        "different_latency_metric",
        "undefined_utilization_direction",
        "unsupported_statistic",
        "period_comparison",
    }:
        return GeneratedSqlResult(
            status="unavailable",
            reason_codes=sorted(codes),
            missing_evidence=[
                "请求依赖尚未提供的数据或超出本版 SQL 方言/时间口径，保留为治理缺口。"
            ],
        )
    if re.search(r"同比|环比|\bp(?:50|90|95|99)\b|中位数|分位数|加权|历史.*状态", question, re.I):
        return GeneratedSqlResult(
            status="unavailable",
            reason_codes=["unsupported_sql_semantics"],
            missing_evidence=["本版生成式 SQL 不开放分位数、跨周期计算、额外权重和历史快照查询。"],
        )
    if re.search(r"本地时间|当地时间|北京时间|local.time", question, re.I) and re.search(
        r"每小时|按小时|hourly|trend|趋势", question, re.I
    ):
        return GeneratedSqlResult(
            status="clarify",
            reason_codes=["bucket_timezone"],
            clarification_question="本版 SQL 时间分桶仅按 UTC 展示；查询窗口仍按请求时区解析。请确认 UTC 分桶，或先补充本地时区分桶支持。",
        )
    return None


def _grounded(value, question):
    return (
        bool(value)
        and re.sub(r"\s+", "", value).casefold() in re.sub(r"\s+", "", question).casefold()
    )


def compile_sql_context(draft, question, now, timezone, previous=None):
    inherited = previous if draft.use_context else None
    named = explicit_devices(question)
    proposed = [d.upper() if re.fullmatch(r"r\d+", d, re.I) else d for d in draft.devices]
    if named and proposed and set(named) != set(proposed):
        raise SqlRejected("Model changed requested devices")
    for device in proposed:
        if (
            not _grounded(device, question)
            and device not in named
            and not (inherited and device in inherited.devices)
        ):
            raise SqlRejected("Model invented a device")
    devices = named or proposed or (list(inherited.devices) if inherited else [])
    all_devices = bool(
        re.search(r"全网|所有设备|全部设备|all devices|network.wide", question, re.I)
    )
    excludes_all = bool(
        re.search(r"(?:不要|不查|不看|别查|不是).{0,4}(?:全网|所有设备|全部设备)", question)
    )
    inherited_all = inherited is not None and inherited.all_devices
    if excludes_all:
        all_devices = inherited_all = False
    if draft.all_devices and not all_devices and not inherited_all:
        raise SqlRejected("Model broadened the device request")
    interfaces = list(
        dict.fromkeys(re.findall(r"(?<![a-z0-9])eth\d+(?![a-z0-9])", question.lower()))
    )
    if len(interfaces) > 1:
        raise SqlContextMissing("本版服务端接口过滤只支持单个接口，请明确一个接口或不限定接口。")
    if (
        draft.interface
        and not _grounded(draft.interface, question)
        and not (inherited and draft.interface == inherited.interface)
    ):
        raise SqlRejected("Model invented an interface")
    if interfaces and draft.interface and draft.interface.casefold() != interfaces[0]:
        raise SqlRejected("Model changed the interface")
    interface = (
        interfaces[0]
        if interfaces
        else draft.interface or (inherited.interface if inherited else None)
    )
    if re.search(r"全部接口|所有接口|不限定接口", question):
        interface = None
    try:
        start, end = resolve_window(question, now, timezone)
    except ValueError:
        raise SqlContextMissing("请明确有效的查询日期和起止时间。") from None
    time_basis = "request" if start else "context" if inherited and inherited.start_utc else "none"
    ignored_model_time = bool(
        draft.time_expression and not _grounded(draft.time_expression, question)
    )
    if ignored_model_time and not start and not (inherited and inherited.start_utc):
        raise SqlRejected("Model invented a time range")
    if start is None and inherited:
        start, end = inherited.start_utc, inherited.end_utc
    severity_aliases = {
        "critical": r"严重|critical",
        "major": r"主要|重要|major",
        "minor": r"次要|minor",
        "warning": r"警告|warning",
    }
    levels = [
        key for key, pattern in severity_aliases.items() if re.search(pattern, question, re.I)
    ]
    if len(levels) > 1:
        raise SqlContextMissing("请明确单个告警级别，或不限定级别。")
    severity = (
        levels[0] if levels else draft.severity or (inherited.severity if inherited else None)
    )
    if draft.severity and levels and draft.severity != levels[0]:
        raise SqlRejected("Model changed severity")
    if (
        severity
        and not re.search(severity_aliases[severity], question, re.I)
        and not (inherited and severity == inherited.severity)
    ):
        raise SqlRejected("Model invented severity")
    if re.search(r"所有级别|不限定级别", question):
        severity = None
    alarm_type = draft.alarm_type
    alarm_aliases = {
        "BGP_NEIGHBOR_DOWN": "BGP",
        "OSPF_ADJACENCY_DOWN": "OSPF",
        "HIGH_UTILIZATION": "高利用率|HIGH_UTILIZATION",
    }
    if (
        alarm_type
        and not re.search(alarm_aliases[alarm_type], question, re.I)
        and not (inherited and alarm_type == inherited.alarm_type)
    ):
        raise SqlRejected("Model invented an alarm type")
    context = SqlRequestContext(
        devices=list(dict.fromkeys(devices)),
        all_devices=not devices and (all_devices or inherited_all),
        interface=interface,
        start_utc=start.astimezone(UTC) if start else None,
        end_utc=end.astimezone(UTC) if end else None,
        timezone=timezone,
        severity=severity,
        alarm_type=alarm_type,
        time_basis=time_basis,
        ignored_model_time_expression=ignored_model_time,
    )
    if not devices and not all_devices and not inherited_all:
        raise SqlContextMissing("请补充设备名称，或明确查询授权范围内的所有设备。", context)
    return context


class GeneratedSqlService:
    def __init__(self, query_service):
        self.query_service = query_service
        self.backend = query_service.backend
        self.settings = query_service.settings

    def prepare(self, draft, question, now, timezone, previous=None):
        if preflight_unavailable(question):
            raise SqlRejected("Unavailable source or semantics")
        context = compile_sql_context(draft, question, now, timezone, previous)
        ast = validate_generated_sql(draft.sql, context, self.settings.sql_max_rows)
        view = next(ast.find_all(exp.Table)).name
        requested_views = {
            definition.view for definition in DEFINITIONS.values() if definition.matches(question)
        }
        if requested_views - {view}:
            raise SqlDataUnavailable(
                "请求同时涉及其他视图的数据，本版单视图 SQL 不省略其中的指标；关联查询需另行扩展。"
            )
        if (
            view not in TIME_COLUMNS
            and context.start_utc
            and not re.search(r"最后已知|最新快照|last.known", question, re.I)
        ):
            raise SqlDataUnavailable(
                "所选状态视图没有采集时间，不作为指定时段的历史设备状态或数量。"
            )
        # Explicit metric names must be present in the source expression, not substituted.
        selected_columns = {
            c.name for selected in ast.expressions for c in selected.find_all(exp.Column)
        }
        for metric in ("packet_loss_pct", "latency_ms", "utilization_pct"):
            if DEFINITIONS[metric].matches(question) and metric not in selected_columns:
                raise SqlRejected("Generated SQL omitted or replaced a requested measure")
            if (
                DEFINITIONS[metric].matches(question)
                and re.search(r"平均|均值|\baverage\b|\bmean\b", question, re.I)
                and not any(
                    metric in {c.name for c in aggregate.find_all(exp.Column)}
                    for aggregate in ast.find_all(exp.Avg)
                )
            ):
                raise SqlRejected("Generated SQL changed an explicitly requested mean")
        parameters = bound_parameters(ast, context, draft.parameters, question)
        try:
            secured, injected = secure_request_sql(ast, context)
        except SqlContextMissing as exc:
            exc.context = context
            raise
        parameters.update(injected)
        return secured, parameters, context, view

    def execute(self, prepared, scope, *, assumptions=()):
        ast, parameters, context, view = prepared
        if not scope.device_ids:
            return GeneratedSqlResult(
                status="forbidden",
                request_context=context,
                reason_codes=["empty_authorized_scope"],
                warnings=["当前身份没有可查询设备。"],
            )
        deadline = time.monotonic() + self.settings.sql_timeout_ms / 1000
        if context.devices:
            for device in context.devices:
                if time.monotonic() > deadline:
                    raise TimeoutError
                result = self.query_service.execute(
                    "SELECT hostname FROM v_device_status WHERE hostname=:requested_device LIMIT 1",
                    {"requested_device": device},
                    scope,
                )
                if not result.rows:
                    return GeneratedSqlResult(
                        status="forbidden",
                        request_context=context,
                        warnings=["设备不在服务端授权范围内。"],
                        reason_codes=["device_scope"],
                    )
        result = self.backend.read(ast, parameters, scope)
        if time.monotonic() > deadline:
            return GeneratedSqlResult(
                status="timeout",
                request_context=context,
                reason_codes=["execution_timeout"],
                missing_evidence=["只读查询超时。"],
            )
        rows = [{key: json_value(value) for key, value in row.items()} for row in result.rows]
        sample_aggregates = [
            selected.alias_or_name
            for selected in ast.expressions
            if selected.find(exp.Avg, exp.Min, exp.Max)
            and any(
                c.name in ("packet_loss_pct", "latency_ms", "utilization_pct")
                for c in selected.find_all(exp.Column)
            )
        ]
        empty_aggregate = bool(
            rows
            and sample_aggregates
            and all(all(row.get(key) is None for key in sample_aggregates) for row in rows)
        )
        output_units = {}
        for selected in ast.expressions:
            columns = {column.name for column in selected.find_all(exp.Column)}
            metrics = columns & {"packet_loss_pct", "latency_ms", "utilization_pct"}
            if selected.find(exp.Count):
                output_units[selected.alias_or_name] = "count"
            elif len(metrics) == 1 and not selected.find(exp.Case):
                output_units[selected.alias_or_name] = DEFINITIONS[next(iter(metrics))].unit
            elif selected.find(exp.TimeToStr, exp.TsOrDsToDate) or columns & set(
                TIME_COLUMNS.values()
            ):
                output_units[selected.alias_or_name] = "UTC"
        evidence = GeneratedSqlEvidence(
            query_id=f"query_{uuid4().hex}",
            executed_at_utc=datetime.now(UTC).isoformat(),
            sql=ast.sql(dialect="mysql"),
            parameters=parameters,
            columns=result.columns,
            output_units=output_units,
            rows=rows,
            row_count=len(rows),
            truncated=result.truncated,
            business_limit=ast.meta.get("requested_limit"),
            row_budget=self.settings.sql_max_rows,
            source_views=[view],
            data_source=self.backend.source,
            catalog_version=CATALOG_VERSION,
            request_context=context,
            assumptions=list(assumptions),
            structural_checks=[
                "single_select",
                "authorized_view_and_columns",
                "bounded_functions",
                "request_predicates",
                "backend_tenant_device_acl",
                "read_only_backend",
                "row_and_time_budget",
            ],
        )
        warnings = [BUSINESS_WARNING, "SQL 时间字段及分桶为 UTC；窗口边界按请求时区转换。"]
        if context.ignored_model_time_expression:
            warnings.append(
                "模型时间说明未采用，实际查询使用服务端从原问题或已确认上下文解析的时间边界。"
            )
        if view not in TIME_COLUMNS:
            warnings.append("状态数据是最后已知快照，不代表实时或指定时段的历史状态。")
        if result.truncated:
            warnings.append("结果达到行数上限，仅展示部分记录。")
        if empty_aggregate:
            warnings.append(
                "SQL 仅返回空采样聚合值（NULL），不将其展示为零或有效测量；原始 SQL 结果仍保留。"
            )
        return GeneratedSqlResult(
            status="ok" if rows and not empty_aggregate else "no_data",
            queries=[evidence],
            request_context=context,
            warnings=warnings,
            missing_evidence=[]
            if rows and not empty_aggregate
            else ["查询没有有效业务记录或非空采样值，无数据不表示指标为零。"],
        )


def database_failure(exc):
    timeout = isinstance(exc, TimeoutError) or (
        isinstance(exc, DBAPIError)
        and any(
            x in str(getattr(exc, "orig", "")).lower()
            for x in ("timeout", "interrupted", "3024", "1317")
        )
    )
    return GeneratedSqlResult(
        status="timeout" if timeout else "error",
        reason_codes=["execution_timeout" if timeout else "database_error"],
        missing_evidence=["只读查询超时。" if timeout else "数据库查询失败（连接信息已隐藏）。"],
    )
