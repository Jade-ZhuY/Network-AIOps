"""Small opt-in real-model smoke test. Never prints or stores credentials."""

import argparse
import json
import statistics
import time

import httpx

from app.config import ROOT, Settings
from scripts.demo import QUESTIONS


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--output", default="outputs/live-smoke.json")
    parser.add_argument(
        "--cleanup", action="store_true", help="Remove only sessions created by this smoke test"
    )
    args = parser.parse_args()
    settings = Settings()
    headers = {"Authorization": "Bearer " + settings.api_auth_token.get_secret_value()}
    rows, sessions = [], []
    with httpx.Client(
        base_url=args.base_url, headers=headers, timeout=settings.request_timeout_seconds + 10
    ) as client:
        for i, question in enumerate(QUESTIONS):
            created = client.post(
                "/api/v1/sessions", json={"title": f"模型验收 {i + 1} · " + question[:50]}
            )
            created.raise_for_status()
            sid = created.json()["session_id"]
            sessions.append(sid)
            start = time.perf_counter()
            response = client.post(
                "/api/v1/chat",
                json={"session_id": sid, "message": question, "timezone": "Asia/Shanghai"},
            )
            response.raise_for_status()
            result = response.json()
            row = {
                "case": i + 1,
                "route": result["route"],
                "status": result["status"],
                "elapsed_seconds": round(time.perf_counter() - start, 3),
                "report_calls": result["report_calls"],
                "checkpoint_saved": result.get("checkpoint_saved", False),
                "hypotheses": len(result["report"]["hypotheses"]),
                "llm_calls": sum(
                    event.get("calls", 0)
                    for event in result["trace"]
                    if event["name"].startswith("llm.")
                ),
                "tokens": sum(
                    event.get("input_tokens", 0) + event.get("output_tokens", 0)
                    for event in result["trace"]
                    if event["name"].startswith("llm.")
                ),
                "error_types": [
                    event["error_type"] for event in result["trace"] if "error_type" in event
                ],
            }
            print(json.dumps(row, ensure_ascii=False))
            rows.append(row)
        if args.cleanup:
            for sid in sessions:
                client.delete("/api/v1/sessions/" + sid).raise_for_status()
    summary = {
        "mode": "live_model_smoke",
        "model": settings.llm_model,
        "sample_count": len(rows),
        "cases": rows,
        "p50_seconds": statistics.median(row["elapsed_seconds"] for row in rows),
        "max_seconds": max(row["elapsed_seconds"] for row in rows),
        "slo_claim": "Only a small smoke sample, not a load-tested P95 estimate",
        "all_success": all(
            row["status"] == "completed" and row["report_calls"] == 1 and row["checkpoint_saved"]
            for row in rows
        ),
    }
    path = (ROOT / args.output).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not summary["all_success"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
