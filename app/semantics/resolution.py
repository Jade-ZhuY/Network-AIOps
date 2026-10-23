"""Bounded language rules and mandatory semantic checks, independent of the LLM."""

import re

from app.semantics.capabilities import capability_issues
from app.semantics.catalog import CATALOG_VERSION, DEFINITIONS
from app.semantics.models import MetricOptions, SemanticIssue

MEAN_CHOICES = ["逐接口采样点等权", "设备级合并采样点等权", "先算每个接口均值，再按接口等权"]
SAMPLE_MEAN = re.compile(
    r"采样(?:点)?等权|样本等权|等权采样|采样均值|sample[_ -]mean|sample[- ]weighted|合并采样", re.I
)
INTERFACE_MEAN = re.compile(
    r"接口等权|先.*接口.*(?:再|然后).*(?:平均|均值)|interface[_ -]mean", re.I
)
PER_INTERFACE = re.compile(r"逐接口|每个接口|各接口分别|按接口分组|device_interface", re.I)
DEVICE = re.compile(
    r"设备级|设备整体|设备总体|按设备汇总|跨接口|合并采样|device[- ]level|pooled", re.I
)
OVERALL = re.compile(r"总体|整体|全网.*平均|设备平均|汇总.*(?:平均|均值)")
WEIGHTED = re.compile(r"加权|weighted|按包数|按发包|包级|总丢包率|丢包包数|丢包数|丢了.*包", re.I)


def is_semantic_reply(question: str) -> bool:
    return bool(
        SAMPLE_MEAN.search(question)
        or INTERFACE_MEAN.search(question)
        or PER_INTERFACE.search(question)
        or re.search(r"最后已知|最新快照|按设备统计", question)
    )


def _selection(text):
    sample, interface = bool(SAMPLE_MEAN.search(text)), bool(INTERFACE_MEAN.search(text))
    if (
        sample
        and interface
        and (re.search(r"还是|或者|\bor\b", text, re.I) or not re.search(r"先|再|然后", text))
    ):
        return None, SemanticIssue(
            code="conflicting_aggregation",
            message="采样点等权与接口等权是两种不同口径，请选择一种。",
            choices=MEAN_CHOICES,
        )
    if interface:
        return MetricOptions(aggregation="interface_mean", grouping="device"), None
    if sample or PER_INTERFACE.search(text):
        return MetricOptions(grouping="device" if DEVICE.search(text) else "device_interface"), None
    if DEVICE.search(text) or OVERALL.search(text):
        return None, SemanticIssue(
            code="ambiguous_aggregation",
            message="设备或全网平均存在歧义：合并采样点求均值，与先算接口均值再等权平均，结果可能不同。请选择统计口径；结果仍按设备分别返回，不生成全网单值。",
            choices=MEAN_CHOICES,
        )
    return None, None


def resolve_options(question: str, metrics: list, inherited: dict | None = None):
    """Explicit metric clauses override a global selection; all options are closed enums."""
    samples = [metric for metric in metrics if DEFINITIONS[metric].kind == "sample"]
    options = {m: option for m, option in (inherited or {}).items() if m in samples}
    issues = []
    if not samples:
        return options, issues
    clauses = [clause for clause in re.split(r"[，,；;。]", question) if clause.strip()]
    global_option = None
    local_options = {}
    for clause in clauses:
        mentioned = [m for m in samples if DEFINITIONS[m].matches(clause)]
        selected, issue = _selection(clause)
        if issue:
            issues.append(issue)
        if selected:
            if mentioned:
                local_options.update(dict.fromkeys(mentioned, selected))
            else:
                global_option = selected
    whole_option, _ = _selection(question)
    two_stage = bool(re.search(r"先.*接口.*(?:再|然后).*(?:平均|均值)", question))
    if whole_option and not local_options and (global_option or two_stage):
        global_option = whole_option
    if two_stage and whole_option and len(samples) == 1:
        local_options[samples[0]] = whole_option
    if global_option:
        options.update(dict.fromkeys(samples, global_option))
    options.update(local_options)
    explicit = set(local_options) | (set(samples) if global_option else set())
    if set(samples).issubset(explicit) and not re.search(r"还是|或者|\bor\b", question, re.I):
        issues = [issue for issue in issues if issue.code != "ambiguous_aggregation"]
    return options, issues


def request_issues(question: str, metrics: list) -> list[SemanticIssue]:
    issues = []
    samples = [metric for metric in metrics if DEFINITIONS[metric].kind == "sample"]
    # Common explicit negation is not a request for the unsupported weighting.
    positive = re.sub(
        r"不(?:要|用|按)?(?:流量|时间|时长|包数)加权|sample[- ]weighted", "", question, flags=re.I
    )
    if samples and WEIGHTED.search(positive):
        issues.append(
            SemanticIssue(
                code="unsupported_weighting",
                message="当前只有百分比/RTT 采样值，没有发包数、丢包数、流量或有效时长权重。加权均值和包级总体丢包率尚无可计算的数据口径。请明确选择现有等权口径，或补充原始计数器及权重定义。",
                choices=MEAN_CHOICES,
            )
        )
    if re.search(r"单向时延|one[- ]way|抖动|jitter", question, re.I):
        issues.append(
            SemanticIssue(
                code="different_latency_metric",
                metric="latency_ms",
                message="现有 latency_ms 定义为往返 RTT，不是单向时延或抖动。请确认查询 RTT，或补充对应采集指标。",
                choices=["查询往返 RTT"],
            )
        )
    traffic_text = re.sub(r"(?:按)?流量加权|traffic[- ]weighted", "", positive, flags=re.I)
    if re.search(
        r"吞吐|\bbps\b|字节数|设备带宽利用率|throughput|\bbytes\b", traffic_text, re.I
    ) or (re.search(r"流量|\btraffic\b", traffic_text, re.I) and "utilization_pct" not in metrics):
        issues.append(
            SemanticIssue(
                code="ambiguous_traffic",
                message="流量可能指 bps 吞吐量、字节数或接口利用率；当前仅有 utilization_pct 百分比采样，收发方向和接口容量口径也未提供。请明确所需指标。",
                choices=["查询接口利用率百分比"],
            )
        )
    if "utilization_pct" in metrics and re.search(
        r"入方向|出方向|接收方向|发送方向|inbound|outbound|\brx\b|\btx\b", question, re.I
    ):
        issues.append(
            SemanticIssue(
                code="undefined_utilization_direction",
                metric="utilization_pct",
                message="源端 utilization_pct 没有提供收发方向与接口容量口径，不将它解释成指定方向的带宽利用率。请确认读取源端接口利用率，或补充方向和容量数据。",
                choices=["查询接口利用率百分比"],
            )
        )
    if samples and re.search(
        r"\bp\s*(?:50|90|95|99)\b|百分位|分位数|中位数|丢包率求和|利用率求和", question, re.I
    ):
        issues.append(
            SemanticIssue(
                code="unsupported_statistic",
                message="当前口径支持均值及采样最小/最大值，不包含分位数、中位数或百分比求和。请明确改用已定义的统计量，或先补充新指标定义。",
                choices=MEAN_CHOICES,
            )
        )
    count_text = re.sub(r"不去重|不按.*去重", "", question)
    if "alarm_count" in metrics and re.search(r"去重|类型数|distinct", count_text, re.I):
        issues.append(
            SemanticIssue(
                code="ambiguous_alarm_count",
                metric="alarm_count",
                message="告警事件数按每条事件计数，不等于去重后的告警类型数或故障数。请确认统计对象。",
                choices=["统计告警事件记录数，不去重"],
            )
        )
    if "incident_summaries" in metrics and re.search(
        r"持续中|仍在|未结束|重叠|overlap|ongoing", question, re.I
    ):
        issues.append(
            SemanticIssue(
                code="incident_time_basis",
                metric="incident_summaries",
                message="当前事件摘要按 started_at 落入窗口筛选，不代表窗口内持续中或与窗口重叠的事件。请确认按开始时间查询，或先定义持续事件口径。",
                choices=["查询窗口内开始的故障记录"],
            )
        )
    snapshots = [metric for metric in metrics if DEFINITIONS[metric].kind == "snapshot"]
    historical = re.search(
        r"昨天|今天|历史|当时|过去|最近|\d{4}-\d{2}-\d{2}|yesterday|today|last\s+\d+",
        question,
        re.I,
    )
    if (
        snapshots
        and historical
        and not re.search(r"最后已知|最新快照|last[- ]known", question, re.I)
    ):
        issues.append(
            SemanticIssue(
                code="snapshot_not_history",
                message="状态源没有采集时间，只保留最后已知快照，不能回答指定时间的历史或实时状态。请确认读取最后已知快照。",
                choices=["查询最后已知状态快照"],
            )
        )
    return issues


def validate_plan_semantics(plan, question: str = "") -> list[SemanticIssue]:
    """Always runs in QueryService, even for plans not produced by the planner."""
    issues = capability_issues(question) + request_issues(question, plan.metrics)
    if not plan.metrics:
        issues.append(
            SemanticIssue(
                code="unknown_metric", message="查询计划没有已定义的指标，不执行空指标查询。"
            )
        )
    if plan.metric_catalog_version is not None and plan.metric_catalog_version != CATALOG_VERSION:
        issues.append(
            SemanticIssue(
                code="catalog_version_mismatch",
                message="查询计划使用的指标目录版本与当前服务不同，请重新确认口径后生成计划。",
            )
        )
    inferred, language_issues = resolve_options(question, plan.metrics)
    issues.extend(language_issues)
    for metric, option in plan.metric_options.items():
        if DEFINITIONS[metric].kind != "sample":
            issues.append(
                SemanticIssue(
                    code="invalid_metric_options",
                    metric=metric,
                    message="此指标不是采样均值指标，不适用采样/接口平均选项。",
                )
            )
        elif option.aggregation == "interface_mean" and option.grouping != "device":
            issues.append(
                SemanticIssue(
                    code="invalid_grouping",
                    metric=metric,
                    message="接口等权均值必须在设备粒度计算。",
                )
            )
    for metric, option in inferred.items():
        if plan.metric_options.get(metric, MetricOptions()) != option:
            issues.append(
                SemanticIssue(
                    code="selection_mismatch",
                    metric=metric,
                    message="查询计划与用户明确选择的聚合口径不一致。",
                )
            )
    if plan.interface and not any("interface_name" in DEFINITIONS[m].filters for m in plan.metrics):
        issues.append(
            SemanticIssue(
                code="unsupported_interface_filter",
                message="所选指标没有接口归属字段，接口条件不会被忽略。请改为按设备查询，或选择有接口维度的指标。",
                choices=["按设备统计，不限定接口"],
            )
        )
    return list({(issue.code, issue.metric): issue for issue in issues}.values())
