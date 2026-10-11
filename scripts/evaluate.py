"""Reproducible pipeline evaluation; live smoke is opt-in, not extrapolated."""

import argparse
import asyncio
import json
import statistics
import time
from copy import deepcopy

from langgraph.checkpoint.memory import InMemorySaver

from app.config import ROOT, Settings
from app.graph.workflow import WorkflowService
from app.schemas.models import Scope
from app.security.auth import Principal
from app.storage.fixtures import demo_records
from app.storage.sessions import MemorySessions


def dataset(name):
    return json.loads((ROOT / "tests" / "datasets" / name).read_text(encoding="utf-8"))


def varying_records(case):
    records = deepcopy(demo_records())
    i = case["variation"]
    device = {"bgp": 2, "ospf": 3, "traffic": 4}[case["family"]]
    for row in records["network_metrics"]:
        if row["device_id"] == device:
            if case["family"] == "bgp" and row["sample_time"].hour in (6, 7, 8):
                row["packet_loss_pct"] = 5.5 + i
                row["latency_ms"] = 35 + 5 * i
            elif case["family"] == "ospf":
                row["packet_loss_pct"] = 0.01 + 0.04 * i
                row["latency_ms"] = 2 + i
            elif case["family"] == "traffic" and row["sample_time"].hour in (6, 7, 8):
                row["utilization_pct"] = 86 + i
                row["latency_ms"] = 45 + 9 * i
    return records


def citation_checks(result, source_map):
    citations = (result["evidence"].get("rag") or {}).get("citations", [])
    return [
        citation["chunk_id"] in source_map
        and citation["text"] == source_map[citation["chunk_id"]].text
        for citation in citations
    ]


async def evaluate():
    settings = Settings(
        _env_file=None, llm_mode="mock", data_backend="mock", persistence_backend="memory"
    )
    sessions = MemorySessions()
    service = WorkflowService(settings, InMemorySaver(), sessions)
    source_map = {chunk.chunk_id: chunk for chunk in service.retriever.chunks}
    counts = {
        "routes": 0,
        "route_correct": 0,
        "sql_queries": 0,
        "sql_success": 0,
        "citations": 0,
        "citations_valid": 0,
        "faults": 0,
        "top3_hit": 0,
        "multi_turn_groups": 0,
        "multi_turn_correct": 0,
    }
    failures, latencies = [], []
    try:
        for case in dataset("routes.json"):
            start = time.perf_counter()
            result = await service.analyze(case["question"])
            latencies.append((time.perf_counter() - start) * 1000)
            counts["routes"] += 1
            counts["route_correct"] += result["route"] == case["expected_route"]
            if result["route"] != case["expected_route"]:
                failures.append(
                    {
                        "case_id": case["case_id"],
                        "error": "route_mismatch",
                        "actual": result["route"],
                    }
                )
            checks = citation_checks(result, source_map)
            counts["citations"] += len(checks)
            counts["citations_valid"] += sum(checks)
            if case["expected_route"] in ("sql", "both"):
                counts["sql_queries"] += 1
                counts["sql_success"] += (result["evidence"]["sql"] or {}).get("status") in (
                    "ok",
                    "no_data",
                )
        phrase = {
            "physical_link_instability": "物理链路不稳定",
            "ospf_parameter_mismatch": "OSPF 参数不匹配",
            "traffic_congestion": "拥塞",
        }
        for case in dataset("fault_cases.json"):
            service.backend.records_factory = lambda case=case: varying_records(case)
            result = await service.analyze(case["question"])
            counts["faults"] += 1
            hypotheses = result["report"]["hypotheses"][:3]
            hit = any(
                phrase[case["ground_truth_root_cause"]] in item["text"] for item in hypotheses
            )
            counts["top3_hit"] += hit
            if not hit:
                failures.append({"case_id": case["case_id"], "error": "root_cause_miss"})
            assert case["must_not_claim"] not in result["report"]["summary"]
        service.backend.records_factory = None
        actor = Principal("eval-user", "engineer", Scope())
        for case in dataset("multi_turn.json"):
            sid = (await sessions.create(actor, case["case_id"], "Asia/Shanghai"))["session_id"]
            for question in case["questions"]:
                result = await service.chat(actor, sid, question, "Asia/Shanghai")
            counts["multi_turn_groups"] += 1
            query = ((result["evidence"]["sql"] or {}).get("queries") or [{}])[0]
            correct = (
                query.get("parameters", {}).get("device_0") == case["expected_final_device"]
                and query.get("metric") == "packet_loss_pct"
            )
            counts["multi_turn_correct"] += correct
            if not correct:
                failures.append({"case_id": case["case_id"], "error": "context_mismatch"})
            await service.delete_session(actor, sid)
    finally:
        service.close()

    def ratio(numerator, denominator):
        return round(counts[numerator] / counts[denominator], 4) if counts[denominator] else None

    return {
        "evaluation_mode": "deterministic_mock_pipeline",
        "not_real_model_quality": True,
        "counts": counts,
        "metrics": {
            "route_accuracy": ratio("route_correct", "routes"),
            "sql_execution_success": ratio("sql_success", "sql_queries"),
            "citation_source_validity": ratio("citations_valid", "citations"),
            "synthetic_root_cause_top3_hit": ratio("top3_hit", "faults"),
            "multi_turn_resolution": ratio("multi_turn_correct", "multi_turn_groups"),
            "mock_p50_ms": round(statistics.median(latencies), 2),
        },
        "limitations": [
            "30 个故障为三个故事的独立数值变体，不是 30 个真实网络事故",
            "引用存在/原文一致性不等同于完整语义支持性人工评分",
            "真实模型质量与 P95 SLO 需单独实测，不从 mock 分数外推",
        ],
        "failures": failures,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="outputs/evaluation.json")
    args = parser.parse_args()
    result = asyncio.run(evaluate())
    path = (ROOT / args.output).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["failures"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
