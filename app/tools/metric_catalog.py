CATALOG = {
    "interface_status": {
        "view": "v_interface_status",
        "unit": None,
        "description": "接口最后已知管理/运行状态（快照，非实时或历史观测）",
    },
    "link_status": {
        "view": "v_link_status",
        "unit": None,
        "description": "两端都在授权范围内的链路最后已知状态（快照）",
    },
    "incident_summaries": {
        "view": "v_incident_summaries",
        "unit": "incidents",
        "description": "查询窗口内开始的事件摘要，不含评估根因标签和修复答案",
    },
    "alarm_count": {
        "view": "v_alarm_events",
        "unit": "count",
        "description": "时间窗内告警数量，按设备聚合（无告警不等价于未采集）",
    },
    "alarm_events": {
        "view": "v_alarm_events",
        "unit": "events",
        "description": "时间窗内告警事件，按发生时间排序",
    },
    "packet_loss_pct": {
        "view": "v_interface_metrics",
        "unit": "%",
        "description": "采样点等权平均丢包百分比；8.0 表示 8%，不是 0.08",
    },
    "latency_ms": {
        "view": "v_interface_metrics",
        "unit": "ms",
        "description": "采样点等权平均 RTT（毫秒）",
    },
    "utilization_pct": {
        "view": "v_interface_metrics",
        "unit": "%",
        "description": "采样点等权平均接口利用率（百分比）",
    },
    "device_status": {
        "view": "v_device_status",
        "unit": None,
        "description": "演示设备最后已知状态，非实时探测",
    },
}
