"""Generated SQL: same ACL backend, stricter single-view policy and request filters."""

import math
import re

from sqlglot import exp, parse_one

from app.schemas.generated_sql import SqlRequestContext
from app.security.sql_guard import SqlRejected, validate_sql
from app.storage.models import VIEW_COLUMNS

TIME_COLUMNS = {
    "v_interface_metrics": "sample_time",
    "v_alarm_events": "occurred_at",
    "v_incident_summaries": "started_at",
}
CRITICAL_COLUMNS = {
    "hostname",
    "peer_hostname",
    "interface_name",
    "peer_interface_name",
    "sample_time",
    "occurred_at",
    "started_at",
    "severity",
    "alarm_type",
}
BUCKET_FORMATS = {"%Y-%m-%d %H:00:00", "%Y-%m-%d", "%Y-%m-%d %H:%M:00"}


class SqlContextMissing(ValueError):
    def __init__(self, message, context=None):
        super().__init__(message)
        self.context = context


class SqlDataUnavailable(ValueError):
    pass


def _date(value):
    return value.strftime("%Y-%m-%d %H:%M:%S.%f")


def _critical_predicates(ast, context):
    for column in ast.find_all(exp.Column):
        if not column.find_ancestor(exp.Where, exp.Having) or column.name not in CRITICAL_COLUMNS:
            continue
        parent = column.parent
        expected = None
        if column.name in ("hostname", "peer_hostname") and context.devices:
            values = {f"device_{i}" for i in range(len(context.devices))}
            if (
                isinstance(parent, exp.In)
                and parent.this is column
                and parent.expressions
                and all(
                    isinstance(e, exp.Placeholder) and e.name in values for e in parent.expressions
                )
            ):
                continue
            expected = values
        elif column.name in ("interface_name", "peer_interface_name") and context.interface:
            expected = {"interface"}
        elif column.name == "severity" and context.severity:
            expected = {"severity"}
        elif column.name == "alarm_type" and context.alarm_type:
            expected = {"alarm_type"}
        elif column.name in TIME_COLUMNS.values() and context.start_utc:
            if (
                isinstance(parent, exp.GTE)
                and parent.this is column
                and isinstance(parent.expression, exp.Placeholder)
                and parent.expression.name == "start"
            ):
                continue
            if (
                isinstance(parent, exp.LT)
                and parent.this is column
                and isinstance(parent.expression, exp.Placeholder)
                and parent.expression.name == "end"
            ):
                continue
        if (
            expected
            and isinstance(parent, exp.EQ)
            and parent.this is column
            and isinstance(parent.expression, exp.Placeholder)
            and parent.expression.name in expected
        ):
            continue
        raise SqlRejected("Use server-bound request filters or omit them for server injection")


def validate_generated_sql(sql, context, max_rows):
    ast = validate_sql(sql, max_rows, allow_time_buckets=True)
    tables = list(ast.find_all(exp.Table))
    if len(tables) != 1 or ast.args.get("joins"):
        raise SqlRejected("Generated SQL currently supports a single authorized view, no joins")
    aliases = [e.alias_or_name for e in ast.expressions]
    if not all(aliases) or len(aliases) != len(set(aliases)):
        raise SqlRejected("Every result column needs a unique name or alias")
    if any(
        alias.startswith(("acl_", "req_")) or alias in ("tenant_id", "peer_tenant_id")
        for alias in aliases
    ):
        raise SqlRejected("Reserved output name")
    for selected in ast.expressions:
        if not list(selected.find_all(exp.Column)) and not selected.find(exp.Count):
            raise SqlRejected("Output expressions must derive from source columns or COUNT")
    for placeholder in ast.find_all(exp.Placeholder):
        if placeholder.name.startswith(("acl_", "req_")):
            raise SqlRejected("Reserved server binding")
    for literal in ast.find_all(exp.Literal):
        if (
            literal.find_ancestor(exp.Where, exp.Having)
            and not literal.find_ancestor(exp.Count, exp.TimeToStr)
            and (list(literal.parent.find_all(exp.Column)) or literal.parent.find(exp.AggFunc))
        ):
            raise SqlRejected("Use value_N bindings for user filter values")
    for function in ast.find_all(exp.TimeToStr):
        if (
            not isinstance(function.args.get("format"), exp.Literal)
            or function.args["format"].this not in BUCKET_FORMATS
        ):
            raise SqlRejected("Unsupported UTC bucket format")
    for temporal in ast.find_all(exp.TimeToStr, exp.TsOrDsToTimestamp, exp.TsOrDsToDate):
        columns = list(temporal.find_all(exp.Column))
        if len(columns) != 1 or columns[0].name != TIME_COLUMNS.get(tables[0].name):
            raise SqlRejected("Time bucketing is only allowed on the view's event/sample time")
        if isinstance(temporal, exp.TsOrDsToTimestamp) and not isinstance(
            temporal.parent, exp.TimeToStr
        ):
            raise SqlRejected("Timestamp conversion is reserved for approved UTC buckets")
    if ast.find(exp.Mul, exp.Div, exp.Pow, exp.Mod):
        raise SqlRejected("Unreviewed arithmetic is outside this generated SQL dialect")
    for aggregate in ast.find_all(exp.Sum):
        if any(
            c.name in ("packet_loss_pct", "latency_ms", "utilization_pct")
            for c in aggregate.find_all(exp.Column)
        ):
            raise SqlRejected("Sample rates/latency must not be summed")
    for coalesce in ast.find_all(exp.Coalesce):
        if any(
            c.name in ("packet_loss_pct", "latency_ms", "utilization_pct")
            for c in coalesce.find_all(exp.Column)
        ):
            raise SqlRejected("Do not fill missing metric observations with constants")
    _critical_predicates(ast, context)
    return ast


def secure_request_sql(ast, context: SqlRequestContext):
    """Inject request constraints even when the model omits WHERE or adds OR 1=1."""
    if not context.devices and not context.all_devices:
        raise SqlContextMissing("请明确设备范围，不将缺少设备条件解释为查询全网。", context)
    secured = ast.copy()
    table = next(secured.find_all(exp.Table))
    view = table.name
    parameters = {}
    predicates = []
    if context.devices:
        for i, device in enumerate(context.devices):
            parameters[f"req_device_{i}"] = device
        values = ", ".join(f":req_device_{i}" for i in range(len(context.devices)))
        host = f"hostname IN ({values})"
        if view == "v_link_status":
            host = f"({host} OR peer_hostname IN ({values}))"
        predicates.append(host)
    time_column = TIME_COLUMNS.get(view)
    if time_column:
        if not context.start_utc or not context.end_utc:
            raise SqlContextMissing("请补充查询时间范围，模型 SQL 不自动猜测日期。")
        parameters.update(req_start=_date(context.start_utc), req_end=_date(context.end_utc))
        predicates += [f"{time_column}>=:req_start", f"{time_column}<:req_end"]
    if context.interface:
        if "interface_name" not in VIEW_COLUMNS[view]:
            raise SqlContextMissing(
                "该视图没有接口归属，请确认按设备查询，或选择有接口维度的数据。"
            )
        parameters["req_interface"] = context.interface
        predicates.append(
            "(interface_name=:req_interface OR peer_interface_name=:req_interface)"
            if view == "v_link_status"
            else "interface_name=:req_interface"
        )
    for key in ("severity", "alarm_type"):
        value = getattr(context, key)
        if value:
            if key not in VIEW_COLUMNS[view]:
                raise SqlRejected("Requested filter not available in the selected view")
            parameters[f"req_{key}"] = value
            predicates.append(f"{key}=:req_{key}")
    # Match source metric null semantics; empty/NULL observations never become zero.
    if view == "v_interface_metrics":
        measured = {column.name for column in ast.find_all(exp.Column)} & {
            "packet_loss_pct",
            "latency_ms",
            "utilization_pct",
        }
        if len(measured) == 1 and ast.find(exp.AggFunc):
            predicates.append(f"{next(iter(measured))} IS NOT NULL")
    columns = ", ".join(VIEW_COLUMNS[view])
    wrapped = parse_one(
        f"SELECT {columns} FROM {view}"
        + (" WHERE " + " AND ".join(predicates) if predicates else ""),
        read="mysql",
    )
    table.replace(
        exp.Subquery(
            this=wrapped, alias=exp.TableAlias(this=exp.to_identifier(table.alias_or_name))
        )
    )
    return secured, parameters


def bound_parameters(ast, context, proposed, question):
    server = {f"device_{i}": d for i, d in enumerate(context.devices)}
    if context.start_utc:
        server.update(start=_date(context.start_utc), end=_date(context.end_utc))
    for key in ("interface", "severity", "alarm_type"):
        if getattr(context, key):
            server[key] = getattr(context, key)
    needed = {p.name for p in ast.find_all(exp.Placeholder)}
    result = {}
    if len(proposed) > 20:
        raise SqlRejected("Parameter budget exceeded")
    for key, value in proposed.items():
        if key in server:
            if value != server[key]:
                raise SqlRejected("Model changed a server-owned parameter")
        elif not re.fullmatch(r"value_\d{1,2}", key):
            raise SqlRejected("Only grounded value_N bindings may come from the model")
        elif isinstance(value, float) and not math.isfinite(value):
            raise SqlRejected("Non-finite parameter")
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            if not re.search(
                r"(?<![\d.])" + re.escape(str(value).removesuffix(".0")) + r"(?![\d.])", question
            ):
                raise SqlRejected("Numeric parameter lacks request evidence")
        elif (
            not isinstance(value, str)
            or not value.strip()
            or value.casefold() not in question.casefold()
        ):
            raise SqlRejected("Text parameter lacks request evidence")
    for key in needed:
        if key in server:
            result[key] = server[key]
        elif key in proposed and re.fullmatch(r"value_\d{1,2}", key):
            result[key] = proposed[key]
        else:
            raise SqlRejected("Missing or forbidden parameter")
    return result
