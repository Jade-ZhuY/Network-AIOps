import asyncio
from uuid import uuid4

from langchain_core.messages import AIMessage
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from app.agents.planning import build_route_plan
from app.agents.runtime import AgentRuntime
from app.config import Settings
from app.observability.tracing import RequestTrace, active_trace
from app.rag.hybrid_retrieval import HybridRetriever, OpenAIEmbedding
from app.rag.ingestion import load_documents
from app.schemas.context import InvocationContext
from app.schemas.models import NetworkReport, QueryPlan, RagResult, RoutePlan, Scope, SqlResult
from app.schemas.state import NetworkState
from app.storage.backends import MemoryBackend, MySQLBackend
from app.tools.sql_readonly import QueryService


def failure_report(state, status, message):
    route = state.get("route", "rag")
    return NetworkReport(
        answer_type={"rag": "knowledge", "sql": "data", "both": "diagnosis"}[route],
        status=status,
        summary=message,
        question=state.get("normalized_question", state["question"]),
        timezone=state["timezone"],
        limitations=["当前未保存会话或 Checkpoint，后续请求需重新提交问题。"],
    )


def build_graph(agent_runtime: AgentRuntime, settings: Settings, checkpointer=None):
    async def supervisor(state, runtime: Runtime[InvocationContext]):
        with runtime.context.trace.span("agent.supervisor") as span:
            try:
                history = [
                    message.content
                    for message in state.get("messages", [])[:-1]
                    if message.type == "human"
                ]
                baseline = build_route_plan(
                    state["question"], settings.demo_now, state["timezone"], history
                )
                plan = await agent_runtime.supervisor(baseline)
                return {
                    "route": plan.route,
                    "normalized_question": plan.normalized_question,
                    "route_plan": plan.model_dump(mode="json"),
                    "rag_result": None,
                    "sql_result": None,
                    "final_report": None,
                    "report_calls": 0,
                }
            except Exception as exc:
                span.update(status="error", error_type=type(exc).__name__)
                # Deliberately do not return exception text / provider URL / credentials.
                plan = RoutePlan(
                    route="rag",
                    normalized_question=state["question"],
                    needs_clarification=True,
                    clarification_question=f"路由处理未完成（{type(exc).__name__}）；请重试或检查模型配置。",
                )
                return {
                    "route": "rag",
                    "normalized_question": state["question"],
                    "route_plan": plan.model_dump(mode="json"),
                    "rag_result": None,
                    "sql_result": None,
                    "final_report": failure_report(
                        state, "failed", plan.clarification_question
                    ).model_dump(mode="json"),
                    "report_calls": 0,
                }

    def select_route(state):
        if state["route_plan"]["needs_clarification"]:
            return "clarify"
        return {"rag": "rag_only", "sql": "sql_only", "both": "dispatch_both"}[state["route"]]

    async def run_rag(state, runtime: Runtime[InvocationContext]):
        with runtime.context.trace.span("agent.rag") as span:
            try:
                result = await agent_runtime.rag(
                    state["route_plan"]["rag_task"], runtime.context.scope, runtime.context.trace
                )
            except Exception as exc:
                span.update(status="error", error_type=type(exc).__name__)
                result = RagResult(
                    status="timeout" if isinstance(exc, TimeoutError) else "error",
                    missing_evidence=[f"知识检索未完成（{type(exc).__name__}）"],
                )
            return {"rag_result": result.model_dump(mode="json")}

    async def run_sql(state, runtime: Runtime[InvocationContext]):
        with runtime.context.trace.span("agent.sql") as span:
            try:
                result = await agent_runtime.sql(
                    state["route_plan"]["sql_task"],
                    QueryPlan.model_validate(state["route_plan"]["query_plan"]),
                    runtime.context.scope,
                    state["timezone"],
                    runtime.context.trace,
                )
            except Exception as exc:
                span.update(status="error", error_type=type(exc).__name__)
                result = SqlResult(
                    status="timeout" if isinstance(exc, TimeoutError) else "error",
                    timezone=state["timezone"],
                    missing_evidence=[f"运维查询未完成（{type(exc).__name__}）"],
                )
            return {"sql_result": result.model_dump(mode="json")}

    async def report(state, runtime: Runtime[InvocationContext]):
        with runtime.context.trace.span("agent.report") as span:
            try:
                payload = {
                    key: state.get(key)
                    for key in (
                        "route",
                        "normalized_question",
                        "timezone",
                        "rag_result",
                        "sql_result",
                    )
                }
                payload.update(llm_mode=settings.llm_mode, data_mode="demo")
                result = await agent_runtime.report(payload)
            except Exception as exc:
                span.update(status="error", error_type=type(exc).__name__)
                result = failure_report(
                    state,
                    "failed",
                    f"报告生成未完成（{type(exc).__name__}）；查询/检索证据保留在本次响应。",
                )
            return {
                "final_report": result.model_dump(mode="json"),
                "report_calls": state.get("report_calls", 0) + 1,
                "messages": [AIMessage(content=result.summary, id=f"answer:{state['request_id']}")],
            }

    def clarify(state):
        result = state.get("final_report") or failure_report(
            state, "needs_clarification", state["route_plan"]["clarification_question"]
        ).model_dump(mode="json")
        return {
            "final_report": result,
            "messages": [AIMessage(content=result["summary"], id=f"answer:{state['request_id']}")],
        }

    builder = StateGraph(NetworkState, context_schema=InvocationContext)
    builder.add_node("supervisor", supervisor)
    builder.add_node("clarify", clarify)
    builder.add_node("dispatch_both", lambda state: {})
    for name in ("rag_only", "rag_parallel"):
        builder.add_node(name, run_rag)
    for name in ("sql_only", "sql_parallel"):
        builder.add_node(name, run_sql)
    for name in ("report_rag", "report_sql", "report_both"):
        builder.add_node(name, report)
        builder.add_edge(name, END)
    builder.add_edge(START, "supervisor")
    builder.add_conditional_edges(
        "supervisor", select_route, ["clarify", "rag_only", "sql_only", "dispatch_both"]
    )
    builder.add_edge("clarify", END)
    builder.add_edge("rag_only", "report_rag")
    builder.add_edge("sql_only", "report_sql")
    builder.add_edge("dispatch_both", "rag_parallel")
    builder.add_edge("dispatch_both", "sql_parallel")
    builder.add_edge(["rag_parallel", "sql_parallel"], "report_both")
    return builder.compile(checkpointer=checkpointer)


class WorkflowService:
    def __init__(self, settings: Settings | None = None, checkpointer=None, sessions=None):
        self.settings = settings or Settings()
        self.sessions = sessions
        self.backend = (
            MemoryBackend(self.settings)
            if self.settings.data_backend == "mock"
            else MySQLBackend(self.settings)
        )
        self.query_service = QueryService(self.backend, self.settings)
        embedding = (
            OpenAIEmbedding(self.settings) if self.settings.embedding_mode == "openai" else None
        )
        self.retriever = HybridRetriever(
            load_documents(self.settings.knowledge_dir), self.settings, embedding
        )
        self.runtime = AgentRuntime(self.settings, self.retriever, self.query_service)
        self.graph = build_graph(self.runtime, self.settings, checkpointer)
        self.stateless_graph = (
            build_graph(self.runtime, self.settings) if checkpointer else self.graph
        )

    async def analyze(
        self,
        question: str,
        timezone: str = "Asia/Shanghai",
        scope: Scope | None = None,
        history: list[str] | None = None,
    ):
        request_id = f"req_{uuid4().hex}"
        trace = RequestTrace(trace_id=f"trace_{uuid4().hex}")
        messages = [{"role": "user", "content": q} for q in (history or [])[-6:] + [question]]
        token = active_trace.set(trace)
        try:
            state = await self.stateless_graph.ainvoke(
                {
                    "question": question,
                    "timezone": timezone,
                    "request_id": request_id,
                    "messages": messages,
                },
                context=InvocationContext(scope or Scope(), trace),
            )
        finally:
            active_trace.reset(token)
        return self.response(state, trace)

    def response(self, state, trace, session_id=None):
        return {
            "request_id": state["request_id"],
            "trace_id": trace.trace_id,
            "route": state["route"],
            "status": state["final_report"]["status"],
            "report": state["final_report"],
            "evidence": {"rag": state.get("rag_result"), "sql": state.get("sql_result")},
            "trace": trace.snapshot(),
            "report_calls": state["report_calls"],
            "persistence_enabled": session_id is not None
            and self.settings.persistence_backend == "postgres",
            "checkpoint_saved": session_id is not None,
            "checkpoint_backend": self.settings.persistence_backend if session_id else "none",
            "session_id": session_id,
        }

    @staticmethod
    def thread_config(principal, session_id):
        return {
            "configurable": {
                "thread_id": f"{principal.scope.tenant_id}:{principal.user_id}:{session_id}"
            }
        }

    async def chat(self, principal, session_id, question, timezone):
        if self.sessions is None:
            raise RuntimeError("Session repository not configured")
        async with self.sessions.lock(session_id, principal):
            request_id = f"req_{uuid4().hex}"
            trace = RequestTrace(f"trace_{uuid4().hex}")
            await self.sessions.start_request(request_id, session_id, principal, question)
            token = active_trace.set(trace)
            try:
                state = await asyncio.wait_for(
                    self.graph.ainvoke(
                        {
                            "question": question,
                            "timezone": timezone,
                            "request_id": request_id,
                            "messages": [
                                {
                                    "role": "user",
                                    "content": question,
                                    "id": f"question:{request_id}",
                                }
                            ],
                        },
                        config=self.thread_config(principal, session_id),
                        context=InvocationContext(principal.scope, trace),
                        durability="sync",
                    ),
                    timeout=self.settings.request_timeout_seconds,
                )
                response = self.response(state, trace, session_id)
            except Exception as exc:
                response = {
                    "request_id": request_id,
                    "session_id": session_id,
                    "trace_id": trace.trace_id,
                    "route": None,
                    "status": "failed",
                    "report": failure_report(
                        {"question": question, "timezone": timezone},
                        "failed",
                        f"执行未完成（{type(exc).__name__}）；可检查依赖并恢复本会话。",
                    ).model_dump(mode="json"),
                    "evidence": {"rag": None, "sql": None},
                    "trace": trace.snapshot(),
                    "report_calls": 0,
                    "persistence_enabled": self.settings.persistence_backend == "postgres",
                    "checkpoint_saved": False,
                    "interrupted": True,
                }
            finally:
                active_trace.reset(token)
            # If saving the response fails, API must surface failure, not claim saved.
            await self.sessions.finish_request(request_id, response)
            return response

    async def resume(self, principal, session_id):
        from app.storage.sessions import SessionMissing

        async with self.sessions.lock(session_id, principal):
            config = self.thread_config(principal, session_id)
            snapshot = await self.graph.aget_state(config)
            if not snapshot.values:
                raise SessionMissing
            trace = RequestTrace(f"trace_{uuid4().hex}")
            token = active_trace.set(trace)
            try:
                state = (
                    await asyncio.wait_for(
                        self.graph.ainvoke(
                            None,
                            config=config,
                            context=InvocationContext(principal.scope, trace),
                            durability="sync",
                        ),
                        self.settings.request_timeout_seconds,
                    )
                    if snapshot.next
                    else snapshot.values
                )
                response = self.response(state, trace, session_id)
                response["restored"] = True
                await self.sessions.finish_request(state["request_id"], response)
                return response
            finally:
                active_trace.reset(token)

    async def delete_session(self, principal, session_id):
        async with self.sessions.lock(session_id, principal):
            await self.graph.checkpointer.adelete_thread(
                self.thread_config(principal, session_id)["configurable"]["thread_id"]
            )
            await self.sessions.delete(session_id, principal)

    def run(self, question, **kwargs):
        return asyncio.run(self.analyze(question, **kwargs))

    def close(self):
        if hasattr(self.backend, "close"):
            self.backend.close()
