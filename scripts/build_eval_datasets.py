"""Fixed labeled fixtures. Labels are scoring inputs, never Agent inputs."""

import json

from app.config import ROOT

RAG = [
    "OSPF 为什么使用链路状态数据库？",
    "OSPF 与 RIP 收敛机制有什么区别？",
    "BGP 邻居 Down 的排查方法是什么？",
    "解释 BGP 协议原理",
    "RIP 距离向量如何工作？",
    "什么是 OSPF LSDB？",
    "BGP Hold Timer 有什么作用？",
    "如何只读核查 BGP TCP 连通性？",
    "OSPF MTU 不匹配怎么排查？",
    "拥塞与高 RTT 的关系是什么？",
    "利用率百分比指标口径是什么？",
    "链路丢包与物理故障怎么区分？",
    "只讲 R2 的 BGP 协议原理，不查询现场数据",
    "如何核对 OSPF Hello 与 Dead 参数？",
    "RIP 跳数度量是什么？",
    "Explain how OSPF works",
    "What is BGP hold timer?",
    "Explain the difference between OSPF and RIP",
    "BGP troubleshooting principles",
    "How does interface loss affect BGP?",
]
SQL = [
    "查询 R2 昨天有多少严重告警",
    "查询R2昨天eth1的平均丢包率",
    "查询 R3 昨天告警事件",
    "查询 R4 昨天下午利用率",
    "查询 R2 最近 24 小时 RTT",
    "查询 R2 在2026-10-10的丢包率",
    "查询 R1 昨天平均时延",
    "查询 R4 昨天平均流量利用率",
    "查询 R2 设备状态",
    "查询所有设备状态",
    "统计 R2 昨天下午告警数量",
    "查询 R3 昨天下午接口丢包率",
    "查询 R4 昨天 eth1 时延",
    "查询 R1 最近24小时利用率",
    "Query R2 alarms yesterday",
    "Query R4 average latency yesterday",
    "Query R2 device status",
    "Query R3 packet loss yesterday",
    "查询 R2 昨天告警及丢包率",
    "查询全网昨天告警",
]
BOTH = [
    "分析 R2 昨天下午 BGP 断连原因",
    "R3 昨天 OSPF 邻居无法建立，为什么？",
    "R4 昨天利用率与 RTT 高，分析原因",
    "分析R2昨天BGP丢包告警原因",
    "R2 最近24小时 BGP 邻居为何断开？",
    "R3 昨天下午 OSPF 可能有什么问题？原因分析",
    "分析 R4 昨天下午流量异常原因",
    "分析 R2 在2026-10-10发生的 BGP 断连原因",
    "R4 昨天链路拥塞的原因是什么？",
    "比较 R2 和 R3 昨天告警与丢包，哪个更异常？",
    "Why did R2 BGP fail yesterday?",
    "Analyze R3 OSPF alarms yesterday",
    "Diagnose R4 traffic latency yesterday",
    "R2 昨天 RTT 增高可能是什么原因？",
    "R3 最近 24 小时邻接故障原因分析",
    "R4 最近 24 小时利用率高，为何？",
    "R2 昨天严重告警与丢包有什么可能原因？",
    "分析 R3 昨天 OSPF 参数不匹配的可能性",
    "分析 R4 昨天下午 RTT 与丢包相关原因",
    "R2 昨天 BGP 告警为何频繁出现？",
]


def build():
    directory = ROOT / "tests" / "datasets"
    routes = [
        dict(case_id=f"route_{route}_{i:02}", question=q, expected_route=route)
        for route, questions in (("rag", RAG), ("sql", SQL), ("both", BOTH))
        for i, q in enumerate(questions)
    ]
    causes = []
    for family, device, label, term in (
        ("bgp", "R2", "physical_link_instability", "BGP 断连与丢包"),
        ("ospf", "R3", "ospf_parameter_mismatch", "OSPF 邻居未建立"),
        ("traffic", "R4", "traffic_congestion", "利用率与 RTT 升高"),
    ):
        for i in range(10):
            causes.append(
                dict(
                    case_id=f"fault_{family}_{i:02}",
                    family=family,
                    variation=i,
                    question=f"分析 {device} 昨天下午 {term} 的可能原因",
                    ground_truth_root_cause=label,
                    fixture_type="synthetic_counterfactual",
                    must_not_claim="已确认唯一根因",
                )
            )
    multi = [
        dict(
            case_id=f"multi_{i:02}",
            questions=[f"查询昨天 {first} 的告警", f"那同一时间 {second} 呢？", "那丢包率呢？"],
            expected_final_device=second,
        )
        for i, (first, second) in enumerate(
            [("R2", "R3"), ("R2", "R4"), ("R3", "R2"), ("R4", "R3")] * 5
        )
    ]
    for name, data in (
        ("routes.json", routes),
        ("fault_cases.json", causes),
        ("multi_turn.json", multi),
    ):
        (directory / name).write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    print(
        f"Fixed datasets: routes={len(routes)}, synthetic_faults={len(causes)}, multi_turn_groups={len(multi)}"
    )


if __name__ == "__main__":
    build()
