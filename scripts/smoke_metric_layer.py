"""Opt-in bounded real-LLM metric planning + read-only database regression."""

import argparse
import asyncio
import json
import time

from app.agents.runtime import AgentRuntime
from app.config import ROOT, Settings
from app.observability.tracing import RequestTrace, active_trace
from app.schemas.models import Scope
from app.storage.backends import MySQLBackend
from app.tools.sql_readonly import QueryService


async def run(limit=12, context_checks=True):
    settings = Settings()
    if settings.llm_mode != "openai" or settings.data_backend != "mysql":
        raise ValueError("This smoke requires explicit live LLM and MySQL settings")
    cases = json.loads(
        (ROOT / "tests" / "datasets" / "metric_intents.json").read_text(encoding="utf-8")
    )[:limit]
    backend = MySQLBackend(settings)
    query = QueryService(backend, settings)
    runtime = AgentRuntime(settings, None, query)
    slots = asyncio.Semaphore(2)

    async def probe(case, previous=None):
        async with slots:
            trace = RequestTrace("metric-smoke-" + case["id"])
            token = active_trace.set(trace)
            started = time.monotonic()
            row = {"id": case["id"], "question": case["question"], "expected_match": case["match"]}
            plan = None
            try:
                plan = await runtime.plan_request(
                    case["question"], settings.demo_now, "Asia/Shanghai", previous=previous
                )
                row.update(
                    metric_match=plan.metric_match.model_dump(mode="json"),
                    query_plan=plan.query_plan.model_dump(mode="json") if plan.query_plan else None,
                )
                row["ok"] = plan.metric_match.status == case["match"]
                if case.get("metrics"):
                    row["ok"] = row["ok"] and set(plan.query_plan.metrics) == set(case["metrics"])
                if case.get("devices"):
                    row["ok"] = row["ok"] and plan.query_plan.devices == case["devices"]
                if plan.metric_match.status == "hit":
                    result = await asyncio.to_thread(
                        query.query, plan.query_plan, Scope(), "Asia/Shanghai", case["question"]
                    )
                    row["sql_status"] = result.status
                    row["queries"] = [e.model_dump(mode="json") for e in result.queries]
                    row["ok"] = row["ok"] and result.status == case.get("sql_status", "ok")
                if case.get("aggregation"):
                    option = plan.query_plan.metric_options.get("packet_loss_pct")
                    row["ok"] = (
                        row["ok"]
                        and option is not None
                        and option.aggregation == case["aggregation"]
                    )
            except Exception as exc:
                row.update(ok=False, error_type=type(exc).__name__)
            finally:
                active_trace.reset(token)
            row["elapsed_seconds"] = round(time.monotonic() - started, 3)
            row["trace"] = trace.snapshot()
            print(
                json.dumps(
                    {
                        key: row[key]
                        for key in ("id", "ok", "elapsed_seconds", "error_type")
                        if key in row
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
            return row, plan

    try:
        pairs = await asyncio.gather(*(probe(case) for case in cases))
        rows = [row for row, _ in pairs]
        by_id = {row["id"]: plan for row, plan in pairs}
        if context_checks:
            for case, previous_id in [
                (
                    {
                        "id": "context_device",
                        "question": "那同一时间 R3 呢？",
                        "match": "hit",
                        "metrics": ["packet_loss_pct"],
                        "devices": ["R3"],
                    },
                    "semantic_loss",
                ),
                (
                    {
                        "id": "context_time",
                        "question": "昨天",
                        "match": "hit",
                        "metrics": ["packet_loss_pct"],
                        "devices": ["R2"],
                    },
                    "missing_time",
                ),
                (
                    {
                        "id": "context_mean",
                        "question": "先算每个接口均值，再按接口等权",
                        "match": "hit",
                        "metrics": ["packet_loss_pct"],
                        "devices": ["R2"],
                        "aggregation": "interface_mean",
                    },
                    "ambiguous_mean",
                ),
            ]:
                previous = by_id.get(previous_id)
                if previous:
                    row, _ = await probe(case, previous)
                    rows.append(row)
        report = {
            "mode": "live_metric_planner_and_readonly_execution",
            "model": settings.llm_model,
            "reference_now_utc": settings.demo_now.isoformat(),
            "cases": rows,
            "passed": sum(row["ok"] for row in rows),
            "total": len(rows),
            "limitations": [
                "Small golden smoke, not universal language coverage or a load/P95 benchmark",
                "Does not exercise RAG or PostgreSQL sessions; scripted tests cover graph/session contracts",
            ],
        }
        path = ROOT / "outputs" / "metric-layer-live.json"
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(
            json.dumps(
                {"passed": report["passed"], "total": report["total"], "output": str(path)},
                ensure_ascii=False,
            )
        )
        return report["passed"] == report["total"]
    finally:
        backend.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--run-live",
        action="store_true",
        help="Explicitly consume configured model API and query the read-only MySQL fixture",
    )
    parser.add_argument("--limit", type=int, default=12, choices=range(1, 13))
    parser.add_argument("--no-context", action="store_true")
    args = parser.parse_args()
    if not args.run_live:
        parser.error("Pass --run-live to run this opt-in smoke")
    if not asyncio.run(run(args.limit, not args.no_context)):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
