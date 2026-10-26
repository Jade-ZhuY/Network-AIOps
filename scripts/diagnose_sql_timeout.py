"""Opt-in SQL-only replay with per-model-round and HTTP timing, without prompt logs.

Reads an existing authorized request/checkpoint and issues bounded live model calls.
Does not edit configuration, write business data, or resume/overwrite the session.
"""

import argparse
import asyncio
import json
import sys
import time
from datetime import UTC, datetime

import httpx
import tiktoken
from langchain_core.callbacks import AsyncCallbackHandler

from app.agents.runtime import AgentRuntime
from app.config import ROOT, Settings
from app.observability.tracing import RequestTrace, active_trace
from app.schemas.models import QueryPlan, RoutePlan
from app.security.auth import principal_from_token
from app.storage.backends import MySQLBackend
from app.storage.checkpoint import postgres_resources
from app.tools.sql_readonly import QueryService
from scripts.http_result import unwrap_result


class TimingProbe(AsyncCallbackHandler):
    """Only timing, counts, tool names and error types; never credentials/content."""

    def __init__(self):
        self.started = time.perf_counter()
        self.events = []
        self.rounds = {}
        self.encoding = tiktoken.get_encoding("cl100k_base")
        self.http_attempts = 0

    def record(self, kind, **fields):
        event = {
            "kind": kind,
            "offset_ms": round((time.perf_counter() - self.started) * 1000, 3),
            **fields,
        }
        self.events.append(event)
        print(json.dumps(event, ensure_ascii=False), flush=True)

    async def on_chat_model_start(self, serialized, messages, *, run_id, **kwargs):
        number = len(self.rounds) + 1
        self.rounds[str(run_id)] = (number, time.perf_counter())
        contents = [m.content for batch in messages for m in batch if isinstance(m.content, str)]
        self.record(
            "model_round_start",
            round=number,
            messages=sum(len(batch) for batch in messages),
            content_chars=sum(len(content) for content in contents),
        )

    async def on_llm_end(self, response, *, run_id, **kwargs):
        number, started = self.rounds[str(run_id)]
        generation = response.generations[0][0]
        message = generation.message
        self.record(
            "model_round_end",
            round=number,
            duration_ms=round((time.perf_counter() - started) * 1000, 3),
            tool_names=[call.get("name") for call in message.tool_calls],
            finish_reason=message.response_metadata.get("finish_reason"),
            usage=message.usage_metadata,
        )

    async def on_llm_error(self, error, *, run_id, **kwargs):
        number, started = self.rounds.get(str(run_id), (None, self.started))
        self.record(
            "model_round_error",
            round=number,
            duration_ms=round((time.perf_counter() - started) * 1000, 3),
            error_type=type(error).__name__,
        )

    async def on_request(self, request):
        self.http_attempts += 1
        attempt = self.http_attempts
        request.extensions["diagnostic_attempt"] = attempt
        body = json.loads(request.content)
        self.record(
            "http_request",
            attempt=attempt,
            sdk_retry_count=request.headers.get("x-stainless-retry-count"),
            body_bytes=len(request.content),
            approximate_body_tokens=len(
                self.encoding.encode(request.content.decode(), disallowed_special=())
            ),
            reasoning_effort=body.get("reasoning_effort"),
        )

        async def transport_event(name, info):
            # Transport trace info may contain headers and URLs: retain names only.
            fields = {"attempt": attempt, "event": name}
            if "exception" in info:
                fields["error_type"] = type(info["exception"]).__name__
            self.record("transport", **fields)

        request.extensions["trace"] = transport_event

    async def on_response(self, response):
        self.record(
            "http_response_headers",
            attempt=response.request.extensions["diagnostic_attempt"],
            status_code=response.status_code,
        )


class DiagnosticRuntime(AgentRuntime):
    def __init__(self, settings, query_service, probe):
        super().__init__(settings, None, query_service)
        self.probe = probe
        self.model_client = None

    def model(self, role):
        model = super().model(role)
        model.callbacks = [self.probe]
        # Instrument the actual runtime client rather than replacing its transport,
        # proxy routing, socket options, connection pool or timeout behavior.
        self.model_client = model.root_async_client._client
        self.model_client.event_hooks["request"].append(self.probe.on_request)
        self.model_client.event_hooks["response"].append(self.probe.on_response)
        transport = self.model_client._transport_for_url(httpx.URL(self.settings.llm_base_url))
        self.probe.record(
            "runtime_transport",
            selected_pool=type(transport._pool).__name__,
            max_retries=model.max_retries,
        )
        return model

    def detach(self):
        if self.model_client is not None:
            self.model_client.event_hooks["request"].remove(self.probe.on_request)
            self.model_client.event_hooks["response"].remove(self.probe.on_response)


async def run(args):
    settings = Settings()
    if settings.llm_mode != "openai" or settings.data_backend != "mysql":
        raise ValueError("This diagnostic requires the configured live model and MySQL")
    if settings.persistence_backend != "postgres":
        raise ValueError("An existing PostgreSQL checkpoint is required")
    token = settings.api_auth_token.get_secret_value()
    principal = principal_from_token(token, settings)
    with httpx.Client(timeout=10) as client:
        response = client.get(
            f"http://127.0.0.1:8080/api/v1/requests/{args.request_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        response.raise_for_status()
        original = unwrap_result(response.json())
    async with postgres_resources(settings) as (_, saver):
        config = {
            "configurable": {
                "thread_id": f"{principal.scope.tenant_id}:{principal.user_id}:{original['session_id']}"
            }
        }
        checkpoint = await saver.aget(config)
    if not checkpoint or checkpoint["channel_values"].get("request_id") != args.request_id:
        raise ValueError("The latest checkpoint does not match the requested replay")
    route = RoutePlan.model_validate(checkpoint["channel_values"]["route_plan"])
    plan = QueryPlan.model_validate(original["response"]["query_plan"])
    if route.query_plan != plan:
        raise ValueError("Stored request and checkpoint query plans disagree")
    backend = MySQLBackend(settings)
    service = QueryService(backend, settings)
    schema = json.dumps(service.schema(), ensure_ascii=False)
    report = {
        "checked_at": datetime.now(UTC).isoformat(),
        "mode": "isolated_live_sql_replay",
        "instrumentation": "callbacks_and_hooks_on_original_runtime_client",
        "source_request_id": args.request_id,
        "configuration_changed": False,
        "session_or_checkpoint_changed": False,
        "model": settings.llm_model,
        "llm_timeout_seconds": settings.llm_timeout_seconds,
        "agent_timeout_seconds": settings.agent_timeout_seconds,
        "max_retries": 1,
        "reasoning_effort": settings.llm_reasoning_effort,
        "schema_chars": len(schema),
        "schema_approximate_tokens": len(
            tiktoken.get_encoding("cl100k_base").encode(schema, disallowed_special=())
        ),
        "schema_views": len(service.schema()["views"]),
        "schema_metrics": len(service.schema()["metrics"]),
        "query_plan": plan.model_dump(mode="json"),
        "original_trace": original["response"]["trace"],
        "replays": [],
    }
    output = ROOT / "outputs" / "sql-timeout-diagnosis-20261022.json"

    def save():
        output.parent.mkdir(exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    try:
        started = time.perf_counter()
        direct = await asyncio.to_thread(
            service.query, plan, principal.scope, original["timezone"], route.sql_task
        )
        report["direct_database_control"] = {
            "duration_ms": round((time.perf_counter() - started) * 1000, 3),
            "status": direct.status,
            "queries": [
                {"metric": query.metric, "row_count": query.row_count} for query in direct.queries
            ],
        }
        save()
        print(json.dumps(report["direct_database_control"], ensure_ascii=False), flush=True)
        for index in range(args.repeats):
            probe = TimingProbe()
            trace = RequestTrace(f"diagnostic-sql-{index + 1}")
            row = {"repeat": index + 1, "events": probe.events}
            report["replays"].append(row)
            context_token = active_trace.set(trace)
            runtime = DiagnosticRuntime(settings, service, probe)
            try:
                result = await runtime.sql(
                    route.sql_task, plan, principal.scope, original["timezone"], trace
                )
                row.update(status=result.status, query_count=len(result.queries))
            except Exception as exc:
                row.update(status="error", error_type=type(exc).__name__)
            finally:
                runtime.detach()
                active_trace.reset(context_token)
                row["duration_ms"] = round((time.perf_counter() - probe.started) * 1000, 3)
                row["trace"] = trace.snapshot()
                save()
                print(
                    json.dumps({k: v for k, v in row.items() if k not in ("events", "trace")}),
                    flush=True,
                )
    finally:
        backend.close()
        save()
    print(f"Evidence: {output}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request-id", required=True)
    parser.add_argument("--repeats", type=int, choices=(1, 2, 3), default=2)
    parser.add_argument("--run-live", action="store_true", required=True)
    args = parser.parse_args()
    factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    with asyncio.Runner(loop_factory=factory) as runner:
        runner.run(run(args))


if __name__ == "__main__":
    main()
