import asyncio
import sys
from contextlib import asynccontextmanager
from uuid import uuid4

import pytest

from app.config import Settings
from app.graph.workflow import WorkflowService
from app.observability.tracing import RequestTrace
from app.rag.management import KnowledgeManager
from app.schemas.context import InvocationContext
from app.schemas.models import Scope
from app.security.auth import Principal
from app.storage.checkpoint import postgres_resources
from app.storage.sessions import PostgresSessions, SessionBusy, SessionMissing

pytestmark = pytest.mark.postgres


def run(coro):
    with asyncio.Runner(
        loop_factory=asyncio.SelectorEventLoop if sys.platform == "win32" else None
    ) as runner:
        return runner.run(coro)


@asynccontextmanager
async def service(**overrides):
    settings = Settings(
        llm_mode="mock",
        data_backend="mysql",
        persistence_backend="postgres",
        embedding_mode="mock",
        **overrides,
    )
    async with postgres_resources(settings) as (pool, saver):
        instance = WorkflowService(settings, saver, PostgresSessions(pool))
        try:
            yield instance
        finally:
            instance.close()


def enabled(request):
    if not request.config.getoption("--run-postgres"):
        pytest.skip("Use --run-postgres for durable integration tests")


def test_restart_restores_context_and_auth(request):
    enabled(request)
    actor = Principal("test-" + uuid4().hex, "engineer", Scope())

    async def first_process():
        async with service() as app:
            sid = (await app.sessions.create(actor, "restart test", "Asia/Shanghai"))["session_id"]
            response = await app.chat(actor, sid, "查询昨天 R2 的告警", "Asia/Shanghai")
            assert response["status"] == "completed" and response["checkpoint_saved"]
            snapshot = await app.graph.aget_state(app.thread_config(actor, sid))
            assert "trace" not in snapshot.values and "scope" not in snapshot.values
            return sid

    sid = run(first_process())

    async def second_process():
        async with service() as app:
            try:
                response = await app.chat(actor, sid, "那同一时间 R3 呢？", "Asia/Shanghai")
                assert response["status"] == "completed"
                assert response["evidence"]["sql"]["queries"][0]["rows"][0]["hostname"] == "R3"
                assert len(await app.sessions.messages(sid, actor)) == 2
                with pytest.raises(SessionMissing):
                    await app.sessions.get(sid, Principal("other", "admin", Scope()))
                state = await app.graph.aget_state(app.thread_config(actor, sid))
                assert len(state.values["messages"]) == 4
            finally:
                await app.delete_session(actor, sid)
            assert not (await app.graph.aget_state(app.thread_config(actor, sid))).values

    run(second_process())


def test_resume_after_supervisor_checkpoint(request):
    enabled(request)
    actor = Principal("test-" + uuid4().hex, "engineer", Scope())

    async def interrupt():
        async with service() as app:
            sid = (await app.sessions.create(actor, "interrupted", "Asia/Shanghai"))["session_id"]
            req = "req_" + uuid4().hex
            question = "分析 R2 昨天下午 BGP 断连原因"
            await app.sessions.start_request(req, sid, actor, question)
            await app.graph.ainvoke(
                {
                    "question": question,
                    "timezone": "Asia/Shanghai",
                    "request_id": req,
                    "messages": [{"role": "user", "content": question}],
                },
                config=app.thread_config(actor, sid),
                context=InvocationContext(actor.scope, RequestTrace("test")),
                interrupt_after=["supervisor"],
                durability="sync",
            )
            snapshot = await app.graph.aget_state(app.thread_config(actor, sid))
            assert snapshot.next
            return sid

    sid = run(interrupt())

    async def resumed():
        async with service() as app:
            try:
                response = await app.resume(actor, sid)
                assert response["status"] == "completed" and response["restored"]
                assert response["report_calls"] == 1
                assert len(await app.sessions.messages(sid, actor)) == 1
            finally:
                await app.delete_session(actor, sid)

    run(resumed())


def test_cross_process_session_lock(request):
    enabled(request)
    actor = Principal("test-" + uuid4().hex, "engineer", Scope())

    async def check():
        async with service() as first, service() as second:
            sid = (await first.sessions.create(actor, "lock", "UTC"))["session_id"]
            try:
                async with first.sessions.lock(sid, actor):
                    with pytest.raises(SessionBusy):
                        async with second.sessions.lock(sid, actor):
                            pass
            finally:
                await first.delete_session(actor, sid)

    run(check())


def test_uploaded_knowledge_survives_new_process_resources(request, tmp_path):
    enabled(request)
    actor = Principal("test-" + uuid4().hex, "admin", Scope())
    marker = "PERSISTED_KNOWLEDGE_" + uuid4().hex

    async def upload():
        async with service(knowledge_upload_dir=tmp_path) as app:
            manager = KnowledgeManager(app, app.sessions, app.settings)
            await manager.rebuild()
            row = await manager.upload(
                "sop.md", "重启知识验收", ("# BGP\n\nBGP 接口证据 " + marker).encode(), actor
            )
            assert row["status"] == "ready"
            return row["doc_id"]

    doc_id = run(upload())

    async def restore():
        async with service(knowledge_upload_dir=tmp_path) as app:
            manager = KnowledgeManager(app, app.sessions, app.settings)
            try:
                await manager.rebuild()
                assert (await manager.get(doc_id, actor))["status"] == "ready"
                citations = app.retriever.search("BGP 接口证据 " + marker, actor.scope).citations
                assert any(item.doc_id == doc_id and marker in item.text for item in citations)
                other = app.retriever.search(marker, Scope(tenant_id="other-tenant")).citations
                assert all(item.doc_id != doc_id for item in other)
            finally:
                await manager.remove(doc_id, actor)

    run(restore())
    assert not list(tmp_path.iterdir())
