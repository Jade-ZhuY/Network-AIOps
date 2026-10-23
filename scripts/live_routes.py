"""Opt-in 60-case real metric-intent Supervisor regression, bounded concurrency."""

import asyncio
import json

from app.agents.runtime import AgentRuntime
from app.config import ROOT, Settings


async def main():
    settings = Settings()
    if settings.llm_mode != "openai":
        raise ValueError("This regression requires a configured live model")
    runtime = AgentRuntime(settings, None, None)
    cases = json.loads((ROOT / "tests" / "datasets" / "routes.json").read_text(encoding="utf-8"))
    slots = asyncio.Semaphore(3)

    async def probe(case):
        async with slots:
            try:
                plan = await runtime.plan_request(
                    case["question"], settings.demo_now, "Asia/Shanghai"
                )
                return {
                    "case_id": case["case_id"],
                    "expected": case["expected_route"],
                    "actual": plan.route,
                    "ok": plan.route == case["expected_route"],
                }
            except Exception as exc:
                return {
                    "case_id": case["case_id"],
                    "expected": case["expected_route"],
                    "actual": None,
                    "ok": False,
                    "error_type": type(exc).__name__,
                }

    results = await asyncio.gather(*(probe(case) for case in cases))
    report = {
        "mode": "live_metric_supervisor_component",
        "model": settings.llm_model,
        "cases": len(results),
        "passed": sum(row["ok"] for row in results),
        "accuracy": sum(row["ok"] for row in results) / len(results),
        "limitations": [
            "LLM proposes metric intent; server grounding, semantic and capability checks decide execution eligibility",
            "This component regression does not measure whole-workflow latency or fault-diagnosis generalization",
        ],
        "failures": [row for row in results if not row["ok"]],
    }
    path = ROOT / "outputs" / "live-routes.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["accuracy"] < 0.9:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
