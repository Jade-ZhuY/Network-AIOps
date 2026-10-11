import asyncio
from uuid import uuid4

from langgraph.graph import END, START, StateGraph

from app.agents.planning import build_route_plan
from app.agents.runtime import AgentRuntime
from app.config import Settings
from app.observability.tracing import RequestTrace
from app.rag.hybrid_retrieval import HybridRetriever, OpenAIEmbedding
from app.rag.ingestion import load_documents
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


def build_graph(runtime: AgentRuntime, settings: Settings):
    async def supervisor(state):
        with state["trace"].span("agent.supervisor") as span:
            try:
                history = [
                    message.content
                    for message in state.get("messages", [])[:-1]
                    if message.type == "human"
                ]
                baseline = build_route_plan(
                    state["question"], settings.demo_now, state["timezone"], history
                )
                plan = await runtime.supervisor(baseline)
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

    async def run_rag(state):
        with state["trace"].span("agent.rag") as span:
            try:
                result = await runtime.rag(
                    state["route_plan"]["rag_task"], state["scope"], state["trace"]
                )
            except Exception as exc:
                span.update(status="error", error_type=type(exc).__name__)
                result = RagResult(
                    status="timeout" if isinstance(exc, TimeoutError) else "error",
                    missing_evidence=[f"知识检索未完成（{type(exc).__name__}）"],
                )
            return {"rag_result": result.model_dump(mode="json")}

    async def run_sql(state):
        with state["trace"].span("agent.sql") as span:
            try:
                result = await runtime.sql(
                    state["route_plan"]["sql_task"],
                    QueryPlan.model_validate(state["route_plan"]["query_plan"]),
                    state["scope"],
                    state["timezone"],
                    state["trace"],
                )
            except Exception as exc:
                span.update(status="error", error_type=type(exc).__name__)
                result = SqlResult(
                    status="timeout" if isinstance(exc, TimeoutError) else "error",
                    timezone=state["timezone"],
                    missing_evidence=[f"运维查询未完成（{type(exc).__name__}）"],
                )
            return {"sql_result": result.model_dump(mode="json")}

    async def report(state):
        with state["trace"].span("agent.report") as span:
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
                result = await runtime.report(payload)
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
            }

    def clarify(state):
        result = state.get("final_report") or failure_report(
            state, "needs_clarification", state["route_plan"]["clarification_question"]
        ).model_dump(mode="json")
        return {"final_report": result}

    builder = StateGraph(NetworkState)
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
    # STOP BEFORE STEP 9. No saver, durable store, or thread/session registry.
    return builder.compile()


class WorkflowService:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or Settings()
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
        self.graph = build_graph(self.runtime, self.settings)

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
        state = await self.graph.ainvoke(
            {
                "question": question,
                "timezone": timezone,
                "request_id": request_id,
                "scope": scope or Scope(),
                "trace": trace,
                "messages": messages,
            }
        )
        return {
            "request_id": request_id,
            "trace_id": trace.trace_id,
            "route": state["route"],
            "status": state["final_report"]["status"],
            "report": state["final_report"],
            "evidence": {"rag": state.get("rag_result"), "sql": state.get("sql_result")},
            "trace": trace.snapshot(),
            "report_calls": state["report_calls"],
            "persistence_enabled": False,
        }

    def run(self, question, **kwargs):
        return asyncio.run(self.analyze(question, **kwargs))

    def close(self):
        if hasattr(self.backend, "close"):
            self.backend.close()
