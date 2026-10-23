"""One reviewed capability contract for planner, matcher and execution preflight."""

import re

from app.semantics.models import SemanticIssue

SUPPORTED_FEATURES = frozenset(
    {
        "window_summary",
        "event_details",
        "status_snapshot",
        "diagnosis",
        "device_comparison",
    }
)
UNSUPPORTED_FEATURES = frozenset(
    {
        "time_series",
        "ranking",
        "percentile",
        "threshold_filter",
        "period_comparison",
        "raw_samples",
        "custom_grouping",
        "weighted_mean",
        "historical_status",
        "other",
    }
)
# A literal utilization/latency alias is not sufficient to reinterpret CPU or memory data.
UNSUPPORTED_METRICS = re.compile(
    r"\b(?:cpu|gpu|memory|disk|temperature|jitter|throughput|bytes|bps)\b|"
    r"处理器|内存|磁盘|温度|电压|电流|光功率|吞吐|字节数|单向时延|抖动|设备带宽利用率",
    re.I,
)
FEATURE_PATTERNS = {
    "time_series": r"每\s*(?:\d+\s*)?(?:分钟|小时|天|日|周|月)|按\s*(?:分钟|小时|天|日|周|月)|趋势|时间序列|折线|\b(?:hourly|daily|weekly|monthly|trend|time.series)\b|by\s+(?:hour|day|week|month)",
    "ranking": r"排名|排行|前\s*[一二三四五六七八九十\d]+|最(?:高|低|严重)的?\s*(?:[一二三四五六七八九十\d]+\s*)?(?:台|个)?(?:设备|接口)|哪个接口.*最|\b(?:top\s*\d*|rank(?:ing)?|bottom\s*\d*)\b",
    "period_comparison": r"同比|环比|比上(?:周|月|年)|增长率|下降率|\b(?:yoy|mom|week.over.week|month.over.month)\b",
    "threshold_filter": r"(?:大于|小于|超过|高于|低于|至少|至多|>=|<=|>|<)\s*\d|\b(?:above|below|greater.than|less.than)\s+\d",
    "custom_grouping": r"按(?:地区|区域|机房|厂商|型号|告警级别|严重级别|告警类型)|\bby\s+(?:region|vendor|severity|alarm.type)\b",
    "raw_samples": r"原始采样|采样明细|逐条采样|\braw\s+(?:samples|metrics)\b",
}
FEATURE_LABELS = {
    "time_series": "时间分桶/趋势查询",
    "ranking": "排名/Top N 查询",
    "period_comparison": "跨周期比较",
    "threshold_filter": "阈值筛选",
    "custom_grouping": "目录外分组维度",
    "raw_samples": "原始采样明细",
    "percentile": "分位数",
    "weighted_mean": "需要额外权重的均值",
    "historical_status": "历史状态",
    "other": "目录外查询方式",
}
DIAGNOSTIC = re.compile(
    r"\bbgp\b|\bospf\b|邻居|邻接|拥塞|链路|丢包|利用率|\brtt\b|latency|traffic|流量", re.I
)


def capability_issues(question: str) -> list[SemanticIssue]:
    issues = []
    unknown = UNSUPPORTED_METRICS.search(question)
    if unknown:
        issues.append(
            SemanticIssue(
                code="unsupported_metric",
                message=f"指标目录没有支持“{unknown.group()}”对应的采集指标；本层未命中，不使用其他指标替代。",
            )
        )
    for feature, pattern in FEATURE_PATTERNS.items():
        if re.search(pattern, question, re.I):
            issues.append(
                SemanticIssue(
                    code=feature,
                    message=f"当前指标执行器尚未实现{FEATURE_LABELS[feature]}，本层未命中，不返回普通均值冒充所需结果。",
                )
            )
    return issues


def feature_issues(features: list[str]) -> list[SemanticIssue]:
    return [
        SemanticIssue(
            code=feature,
            message=f"当前指标执行器尚未实现{FEATURE_LABELS.get(feature, feature)}，本层未命中。",
        )
        for feature in features
        if feature not in SUPPORTED_FEATURES
    ]


def capabilities_document() -> dict:
    return {
        "supported_features": sorted(SUPPORTED_FEATURES),
        "unsupported_features": sorted(UNSUPPORTED_FEATURES),
        "matching_outcomes": ["hit", "clarify", "miss"],
        "miss_next_layer": "text_to_sql",
        "fallback_connected": True,
        "sql_cache_enabled": False,
    }
