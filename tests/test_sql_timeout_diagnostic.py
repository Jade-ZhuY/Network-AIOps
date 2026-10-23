import asyncio
import json
from types import SimpleNamespace
from uuid import uuid4

import httpx
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, LLMResult

from app.agents.runtime import AgentRuntime
from app.config import Settings
from scripts.diagnose_sql_timeout import DiagnosticRuntime, TimingProbe


async def test_model_timing_does_not_record_prompt_or_exception_message():
    probe = TimingProbe()
    secret = "PRIVATE_PROMPT_AND_KEY_12345"
    run_id = uuid4()
    await probe.on_chat_model_start({}, [[HumanMessage(content=secret)]], run_id=run_id)
    await probe.on_llm_error(TimeoutError(secret), run_id=run_id)
    assert secret not in json.dumps(probe.events)
    assert probe.events[0]["content_chars"] == len(secret)
    assert probe.events[1]["error_type"] == "TimeoutError"
    assert probe.events[1]["duration_ms"] >= 0


async def test_model_end_records_tool_name_and_usage_not_arguments_or_content():
    probe = TimingProbe()
    run_id = uuid4()
    await probe.on_chat_model_start({}, [[HumanMessage(content="test")]], run_id=run_id)
    usage = {"input_tokens": 10, "output_tokens": 2, "total_tokens": 12}
    message = AIMessage(
        content="PRIVATE_OUTPUT",
        tool_calls=[{"name": "get_schema", "args": {"test": "PRIVATE_ARG"}, "id": "call-1"}],
        response_metadata={"finish_reason": "tool_calls"},
        usage_metadata=usage,
    )
    await probe.on_llm_end(
        LLMResult(generations=[[ChatGeneration(message=message)]]), run_id=run_id
    )
    event = probe.events[-1]
    assert event["tool_names"] == ["get_schema"]
    assert event["usage"] == usage
    assert "PRIVATE_OUTPUT" not in json.dumps(probe.events)
    assert "PRIVATE_ARG" not in json.dumps(probe.events)


async def test_http_probe_records_retry_without_headers_urls_or_payloads():
    probe = TimingProbe()
    request = httpx.Request(
        "POST",
        "https://private.example/v1/chat/completions",
        headers={"Authorization": "Bearer PRIVATE_TOKEN", "x-stainless-retry-count": "1"},
        json={"messages": [{"role": "user", "content": "PRIVATE_QUESTION"}]},
    )
    await probe.on_request(request)
    await request.extensions["trace"](
        "http11.receive_response_headers.failed",
        {"exception": httpx.ReadTimeout("PRIVATE_ERROR"), "headers": "PRIVATE_HEADERS"},
    )
    await probe.on_response(httpx.Response(503, request=request))
    serialized = json.dumps(probe.events)
    for value in ("PRIVATE_", "private.example", "Authorization", "Bearer"):
        assert value not in serialized
    assert probe.events[0]["sdk_retry_count"] == "1"
    assert probe.events[1]["error_type"] == "ReadTimeout"
    assert probe.events[2]["status_code"] == 503


async def test_probe_records_model_cancellation():
    probe = TimingProbe()
    run_id = uuid4()
    await probe.on_chat_model_start({}, [[HumanMessage(content="test")]], run_id=run_id)
    await probe.on_llm_error(asyncio.CancelledError(), run_id=run_id)
    assert probe.events[-1]["error_type"] == "CancelledError"


def test_diagnostic_instruments_original_client_and_detaches_only_its_hooks(monkeypatch):
    existing_hook = object()
    client = SimpleNamespace(
        event_hooks={"request": [existing_hook], "response": []},
        _transport_for_url=lambda _: SimpleNamespace(_pool=SimpleNamespace()),
    )
    original_model = SimpleNamespace(
        callbacks=None, root_async_client=SimpleNamespace(_client=client), max_retries=1
    )
    monkeypatch.setattr(AgentRuntime, "model", lambda *_: original_model)
    probe = TimingProbe()
    runtime = DiagnosticRuntime(Settings(_env_file=None), None, probe)
    assert runtime.model("sql") is original_model
    assert original_model.max_retries == 1
    assert original_model.callbacks == [probe]
    assert client.event_hooks["request"] == [existing_hook, probe.on_request]
    runtime.detach()
    assert client.event_hooks == {"request": [existing_hook], "response": []}
