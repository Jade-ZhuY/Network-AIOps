"""Deterministic mock planner and time/entity constraints for live structured plans."""

import re
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.schemas.models import QueryPlan, RoutePlan

MUTATION = re.compile(
    r"删除|修改|清空|重置|系统账号|密码|\b(drop|delete|truncate|update|insert)\b|;\s*select|--|/\*",
    re.I,
)


def resolve_window(question: str, now: datetime, timezone: str):
    zone = ZoneInfo(timezone)
    local_now = now.astimezone(zone)
    dates = re.findall(r"(?<![0-9])\d{4}-\d{2}-\d{2}(?![0-9])", question)
    if dates:
        start_day = datetime.strptime(dates[0], "%Y-%m-%d").date()
        end_day = (
            datetime.strptime(dates[1], "%Y-%m-%d").date()
            if len(dates) > 1
            else start_day + timedelta(days=1)
        )
        start = datetime.combine(start_day, time.min, zone)
        end = datetime.combine(end_day, time.min, zone)
    elif "昨天" in question or "yesterday" in question.lower():
        day = local_now.date() - timedelta(days=1)
        start, end = (
            datetime.combine(day, time.min, zone),
            datetime.combine(day + timedelta(days=1), time.min, zone),
        )
    elif "今天" in question or "today" in question.lower():
        start = datetime.combine(local_now.date(), time.min, zone)
        end = local_now
    else:
        match = re.search(r"(?:最近|过去|last|past)\s*(\d+)\s*(?:小时|hours?|h)", question, re.I)
        if match:
            hours = int(match[1])
            if not 1 <= hours <= 720:
                raise ValueError("Time window outside 1–720 hours")
            return now - timedelta(hours=hours), now
        if any(term in question for term in ("最近一天", "最近24小时", "过去一天")):
            return now - timedelta(days=1), now
        return None, None
    if "下午" in question or "afternoon" in question.lower():
        start = datetime.combine(start.date(), time(12), zone)
        end = datetime.combine(start.date(), time(18), zone)
    return start.astimezone(UTC), end.astimezone(UTC)


def build_route_plan(
    question: str, now: datetime, timezone: str, history: list[str] | None = None
) -> RoutePlan:
    q = question.strip()
    lower = q.lower()
    history = (history or [])[-6:]
    previous = None
    for index, prior in enumerate(history):
        candidate = build_route_plan(prior, now, timezone, history[:index])
        if candidate.query_plan and not candidate.needs_clarification:
            previous = candidate
    devices = list(dict.fromkeys(re.findall(r"(?<![A-Z0-9])R\d+(?![A-Z0-9])", q.upper())))
    followup = any(
        term in q for term in ("同一时间", "同样", "那", "两台", "它", "呢", "比较")
    ) or any(term in lower for term in ("same time", "what about", "compare"))
    knowledge = any(
        term in lower
        for term in (
            "原理",
            "区别",
            "机制",
            "是什么",
            "如何",
            "排查方法",
            "what is",
            "how does",
            "difference",
            "explain",
        )
    )
    data_signal = bool(devices) or any(
        term in lower
        for term in (
            "查询",
            "多少",
            "告警",
            "平均",
            "统计",
            "最近",
            "昨天",
            "today",
            "yesterday",
            "query",
            "alarms",
            "average",
        )
    )
    causal = any(
        term in lower
        for term in (
            "分析",
            "原因",
            "为何",
            "为什么",
            "analy",
            "diagnos",
            "cause",
            "why",
            "compare",
            "比较",
        )
    )
    explicit_knowledge = any(
        term in q for term in ("只讲", "只问", "仅解释", "不查询现场", "只解释")
    )
    if knowledge and (not devices or explicit_knowledge):
        route = "rag"
    elif MUTATION.search(q):
        route = "sql"
    elif data_signal or (followup and previous):
        route = "both" if causal else "sql"
    else:
        route = "rag"
    if route == "rag":
        return RoutePlan(route=route, normalized_question=q, rag_task=q)
    if MUTATION.search(q):
        return RoutePlan(
            route="sql",
            normalized_question=q,
            sql_task=q,
            query_plan=QueryPlan(metrics=["device_status"]),
        )
    inherited = previous.query_plan if followup and previous else None
    if not devices and inherited:
        devices = inherited.devices
    if "两台" in q or "比较" in q or "compare" in lower:
        devices = (
            list(
                dict.fromkeys(
                    re.findall(
                        r"(?<![A-Z0-9])R\d+(?![A-Z0-9])", " ".join(history[-2:] + [q]).upper()
                    )
                )
            )
            or devices
        )
    interface_match = re.search(r"(?<![a-z0-9])eth\d+(?![a-z0-9])", lower)
    interface = (
        interface_match.group() if interface_match else inherited.interface if inherited else None
    )
    try:
        start, end = resolve_window(q, now, timezone)
    except ValueError:
        return RoutePlan(
            route=route,
            normalized_question=q,
            needs_clarification=True,
            clarification_question="请提供有效日期或 1–720 小时内的查询窗口。",
        )
    if not start and inherited:
        start, end = inherited.start_utc, inherited.end_utc
    metrics = []
    if "告警" in q or "alarm" in lower:
        metrics.append(
            "alarm_count"
            if any(term in q for term in ("多少", "数量", "几条", "统计")) or "count" in lower
            else "alarm_events"
        )
    for terms, metric in (
        (("丢包", "loss"), "packet_loss_pct"),
        (("时延", "rtt", "latency"), "latency_ms"),
        (("利用率", "流量", "utilization", "traffic"), "utilization_pct"),
        (("设备状态", "device status"), "device_status"),
    ):
        if any(term in lower for term in terms):
            metrics.append(metric)
    if route == "both":
        metrics = list(
            dict.fromkeys(
                metrics + ["alarm_events", "packet_loss_pct", "latency_ms", "utilization_pct"]
            )
        )
    if not metrics:
        metrics = inherited.metrics if inherited else ["alarm_events"]
    all_devices = (
        any(term in q for term in ("所有设备", "全网", "全部设备")) or "all devices" in lower
    )
    missing = []
    if not devices and not all_devices:
        missing.append("设备名称（例如 R2）")
    if not start and any(metric != "device_status" for metric in metrics):
        missing.append("查询时间范围及日期")
    if missing:
        return RoutePlan(
            route=route,
            normalized_question=q,
            needs_clarification=True,
            clarification_question="请补充" + "、".join(missing) + "。",
        )
    severity = "critical" if "严重" in q or "critical" in lower else None
    plan = QueryPlan(
        devices=devices,
        interface=interface,
        start_utc=start,
        end_utc=end,
        metrics=metrics,
        severity=severity or (inherited.severity if inherited else None),
    )
    normalized = q + f" [设备={','.join(devices) or '授权范围全部设备'}; 时区={timezone}"
    if start:
        normalized += f"; UTC时间窗=[{start.isoformat()}, {end.isoformat()})"
    normalized += "]"
    return RoutePlan(
        route=route,
        normalized_question=normalized,
        rag_task=q if route == "both" else None,
        sql_task=normalized,
        query_plan=plan,
    )
