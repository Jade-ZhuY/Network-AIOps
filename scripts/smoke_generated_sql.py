"""Explicit live SQL-authoring + readonly MySQL smoke; not the historical SQL cache."""

import argparse
import asyncio
import json
import time

from app.agents.planning import build_route_plan
from app.agents.runtime import AgentRuntime
from app.config import ROOT, Settings
from app.observability.tracing import RequestTrace, active_trace
from app.schemas.models import Scope
from app.storage.backends import MySQLBackend
from app.tools.sql_readonly import QueryService

CASES = [
    ("ranking", "查询 R2 昨天按平均丢包率排名前3的接口", "ok"),
    ("hourly", "查询 R2 昨天每小时丢包率趋势", "ok"),
    ("threshold", "查询 R2 昨天平均丢包率超过5%的接口", "ok"),
    ("alarm_type", "查询 R2 昨天按告警类型统计数量", "ok"),
    ("raw_samples", "查询 R2 昨天原始丢包率采样明细", "ok"),
    ("unauthorized", "查询 R99 昨天按平均丢包率排名前3的接口", "forbidden"),
    ("source_missing", "查询 R2 昨天 CPU 温度", "unavailable"),
    ("no_data", "查询 R2 2030-01-01 按平均丢包率排名前3的接口", "no_data"),
]


async def run():
    settings = Settings()
    if settings.llm_mode != "openai" or settings.data_backend != "mysql":
        raise ValueError("Requires explicitly configured live model and MySQL")
    backend = MySQLBackend(settings)
    runtime = AgentRuntime(settings, None, QueryService(backend, settings))
    slots = asyncio.Semaphore(2)

    async def probe(case):
        name, question, expected = case
        async with slots:
            trace = RequestTrace("generated-sql-smoke-" + name)
            token = active_trace.set(trace)
            start = time.monotonic()
            row = {"id": name, "question": question, "expected_status": expected}
            try:
                # Explicit rule fixture for layer-1 miss, real model for SQL authoring.
                plan = build_route_plan(question, settings.demo_now, "Asia/Shanghai")
                result = await runtime.generated_sql(
                    question, Scope(), "Asia/Shanghai", trace, metric_match=plan.metric_match
                )
                row.update(result=result.model_dump(mode="json"), ok=result.status == expected)
                if result.status == "ok":
                    row["ok"] = row["ok"] and bool(result.queries and result.queries[0].rows)
                    if name == "ranking":
                        row["ok"] = row["ok"] and all(
                            r.get("hostname") == "R2" for r in result.queries[0].rows
                        )
                    if name == "hourly":
                        row["ok"] = row["ok"] and len(result.queries[0].rows) == 5
            except Exception as exc:
                row.update(ok=False, error_type=type(exc).__name__)
            finally:
                active_trace.reset(token)
            row.update(elapsed_seconds=round(time.monotonic() - start, 3), trace=trace.snapshot())
            print(
                json.dumps(
                    {k: row[k] for k in ("id", "ok", "elapsed_seconds", "error_type") if k in row},
                    ensure_ascii=False,
                ),
                flush=True,
            )
            return row

    try:
        cases = await asyncio.gather(*(probe(case) for case in CASES))
        report = {
            "mode": "live_generated_sql_and_readonly_mysql",
            "model": settings.llm_model,
            "metric_gate": "explicit_rule_fixture",
            "cases": cases,
            "passed": sum(c["ok"] for c in cases),
            "total": len(cases),
            "limitations": [
                "Small SQL-role golden smoke, not universal business correctness or P95 validation",
                "No application PostgreSQL/RAG initialization; graph routing covered by separate tests",
                "No historical SQL example cache",
            ],
        }
        path = ROOT / "outputs" / "generated-sql-live.json"
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


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--run-live",
        action="store_true",
        help="Consume configured model API and query read-only fixture views",
    )
    if not parser.parse_args().run_live:
        parser.error("Pass --run-live to run the explicit live smoke")
    if not asyncio.run(run()):
        raise SystemExit(1)
