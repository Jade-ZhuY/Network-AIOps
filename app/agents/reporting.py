"""Evidence-derived claims; mock composition and live-output grounding use the same contract."""

from app.schemas.models import Claim, Hypothesis, NetworkReport, RagResult, SqlResult


def evidence_report(payload: dict) -> NetworkReport:
    route = payload["route"]
    rag = RagResult.model_validate(payload["rag_result"]) if payload.get("rag_result") else None
    sql = SqlResult.model_validate(payload["sql_result"]) if payload.get("sql_result") else None
    facts, hypotheses, refs, limitations, freshness = [], [], [], [], []
    next_checks = []
    metric_rows = {}
    alarms = []
    if sql:
        limitations.extend(sql.warnings + sql.missing_evidence)
        for query in sql.queries:
            if not query.rows:
                continue
            refs.append(query.query_id)
            if query.data_freshness_utc:
                freshness.append(f"{query.query_id}: {query.data_freshness_utc} UTC")
            for row in query.rows:
                if query.metric == "alarm_events":
                    text = f"{row['hostname']} 在 {row['occurred_at']} UTC 出现 {row['severity']} / {row['alarm_type']} 告警（alarm_id={row['alarm_id']}）。"
                    alarms.append((row["hostname"], row["alarm_type"], query.query_id))
                elif query.metric == "alarm_count":
                    text = f"{row['hostname']} 在查询时间窗内有 {row['alarm_count']} 条匹配告警。"
                elif query.metric == "device_status":
                    text = f"{row['hostname']} 最后已知状态为 {row['status']}，区域 {row['region']}；不代表实时探测。"
                elif query.metric == "interface_status":
                    text = f"{row['hostname']} / {row['interface_name']} 最后已知管理状态 {row['admin_status']}、运行状态 {row['oper_status']}；不代表实时或历史观测。"
                elif query.metric == "link_status":
                    text = f"链路 {row['link_id']}：{row['hostname']} / {row['interface_name']} ↔ {row['peer_hostname']} / {row['peer_interface_name']}，最后已知状态 {row['link_status']}。"
                elif query.metric == "incident_summaries":
                    text = f"事件 {row['incident_id']}：{row['hostname']}，开始于 {row['started_at']} UTC，现象：{row['symptom']}。"
                else:
                    text = f"{row['hostname']} / {row['interface_name']} 的 {query.metric} 等权采样均值为 {row['average_value']:.3f} {query.unit}，范围 {row['min_value']:.3f}–{row['max_value']:.3f} {query.unit}，采样数 {row['sample_count']}。"
                    metric_rows.setdefault(row["hostname"], {})[query.metric] = (
                        row,
                        query.query_id,
                    )
                facts.append(Claim(text=text, evidence_refs=[query.query_id]))
    if rag:
        limitations.extend(rag.missing_evidence)
        for citation in rag.citations:
            refs.append(citation.chunk_id)
            if route == "rag":
                facts.append(
                    Claim(
                        text=f"知识来源《{citation.title}》/{citation.section}: {citation.text}",
                        evidence_refs=[citation.chunk_id],
                    )
                )
            freshness.append(f"{citation.doc_id}: 文档更新 {citation.updated_at}")
    # These thresholds illustrate fixture hypotheses, not universal operating limits.
    if route == "both" and sql and rag and rag.citations:
        for device, metrics in metric_rows.items():
            device_alarms = [(kind, ref) for host, kind, ref in alarms if host == device]
            loss = metrics.get("packet_loss_pct")
            rtt = metrics.get("latency_ms")
            utilization = metrics.get("utilization_pct")
            cases = []
            if (
                loss
                and loss[0]["max_value"] >= 5
                and any(kind == "BGP_NEIGHBOR_DOWN" for kind, _ in device_alarms)
            ):
                cases.append(
                    (
                        "sop-bgp",
                        f"{device} 的接口丢包与 BGP 断连同时出现，物理链路不稳定是待验证假设；也需区分拥塞和对端故障。",
                        [loss[1]]
                        + [ref for kind, ref in device_alarms if kind == "BGP_NEIGHBOR_DOWN"],
                        "只读核查两端接口 CRC/FCS、flap 日志、TCP 179 连通性与 BGP 定时器。",
                    )
                )
            if (
                loss
                and loss[0]["max_value"] < 1
                and any(kind == "OSPF_ADJACENCY_DOWN" for kind, _ in device_alarms)
            ):
                cases.append(
                    (
                        "sop-ospf",
                        f"{device} 低丢包条件下仍有 OSPF 邻接告警，可核查 OSPF 参数不匹配；目前没有配置证据确认具体参数。",
                        [loss[1]]
                        + [ref for kind, ref in device_alarms if kind == "OSPF_ADJACENCY_DOWN"],
                        "只读比对 area、Hello/Dead、认证、网络类型和 MTU。",
                    )
                )
            if (
                utilization
                and rtt
                and utilization[0]["max_value"] >= 85
                and rtt[0]["max_value"] >= 30
            ):
                cases.append(
                    (
                        "sop-traffic",
                        f"{device} 高利用率与高 RTT 同时出现，拥塞是待验证解释之一；相关性不证明因果关系。",
                        [utilization[1], rtt[1]],
                        "只读获取队列丢弃、流量分布、路径变化与对端负荷。",
                    )
                )
            for doc_id, text, sql_refs, check in cases:
                citation = next((c for c in rag.citations if c.doc_id == doc_id), None)
                if citation:
                    hypotheses.append(
                        Hypothesis(
                            text=text,
                            evidence_refs=list(dict.fromkeys(sql_refs + [citation.chunk_id])),
                            strength="to_verify",
                        )
                    )
                    next_checks.append(check)
        limitations.append("未取得对端实时状态、完整配置和物理错误计数；现有相关性未确认唯一根因。")
        if not hypotheses:
            next_checks.append(
                "继续收集同一时间窗的对端日志、接口物理计数与协议配置，再提出原因假设。"
            )
    requested = [rag] if route == "rag" else [sql] if route == "sql" else [rag, sql]
    statuses = [result.status if result else "error" for result in requested]
    has_evidence = bool(facts or (rag and rag.citations))
    if all(status == "ok" for status in statuses) and has_evidence:
        status = "completed"
    elif has_evidence:
        status = "partial"
    elif any(status in ("error", "timeout", "forbidden") for status in statuses):
        status = "failed"
    else:
        status = "no_evidence"
    if route == "rag":
        summary = (
            "\n".join(f.text for f in facts[:2])
            if facts
            else "没有检索到支持该问题的授权文档证据。"
        )
    elif facts:
        summary = "\n".join(f.text for f in facts[:3])
        if route == "both":
            summary += "\n" + (
                hypotheses[0].text if hypotheses else "现有证据不足以提出有支持的具体根因。"
            )
    else:
        summary = "本次没有取得可用的运维事实；请查看查询状态与证据缺口。"
    if status != "completed":
        summary += "\n部分查询/检索未成功或没有证据，结果不代表完整调查。"
    limitations.append("知识资料为自编演示 SOP/笔记，检索分数不是根因概率。")
    if payload.get("llm_mode") == "mock":
        limitations.append("当前使用确定性 mock 模型；未验证真实模型推理质量。")
    if payload.get("data_mode", "demo") == "demo":
        limitations.append("当前运维记录为演示数据，非实际网络采集。")
    return NetworkReport(
        answer_type={"rag": "knowledge", "sql": "data", "both": "diagnosis"}[route],
        status=status,
        summary=summary,
        question=payload["normalized_question"],
        timezone=payload["timezone"],
        time_range_utc=sql.time_range_utc if sql else [],
        facts=facts,
        hypotheses=hypotheses,
        next_checks=list(dict.fromkeys(next_checks)),
        limitations=list(dict.fromkeys(limitations)),
        evidence_refs=list(dict.fromkeys(refs)),
        data_freshness=list(dict.fromkeys(freshness)),
        data_mode=payload.get("data_mode", "demo"),
    )


def validate_report(report: NetworkReport, payload: dict) -> NetworkReport:
    canonical = evidence_report(payload)
    allowed_refs = set(canonical.evidence_refs)
    allowed_facts = {claim.text: claim.evidence_refs for claim in canonical.facts}
    allowed_hypotheses = {claim.text: claim.evidence_refs for claim in canonical.hypotheses}
    if not set(report.evidence_refs).issubset(allowed_refs):
        raise ValueError("Report references evidence not returned by tools")
    for claim in report.facts:
        if claim.text not in allowed_facts or claim.evidence_refs != allowed_facts[claim.text]:
            raise ValueError("Report contains an ungrounded factual claim")
    for claim in report.hypotheses:
        if (
            claim.text not in allowed_hypotheses
            or claim.evidence_refs != allowed_hypotheses[claim.text]
            or claim.strength != "to_verify"
        ):
            raise ValueError("Report contains an unsupported hypothesis")
    # Current milestone uses a conservative evidence renderer for every user-visible
    # statement; live LLM output must match the permitted grounded report contract.
    if report != canonical:
        raise ValueError("Report deviates from the evidence-grounded contract")
    return report
