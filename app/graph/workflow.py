import asyncio
import re
from contextlib import asynccontextmanager
from copy import deepcopy
from uuid import uuid4

from langchain_core.messages import AIMessage
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from app.agents.generated_sql import generated_sql_report
from app.agents.planning import build_route_plan, resolve_window
from app.agents.runtime import AgentRuntime
from app.config import Settings
from app.governance.feedback import GovernanceFeedbackService
from app.observability.tracing import RequestTrace, active_trace
from app.rag.hybrid_retrieval import HybridRetriever, OpenAIEmbedding
from app.rag.ingestion import load_documents
from app.schemas.context import InvocationContext
from app.schemas.generated_sql import GeneratedSqlResult, SqlRequestContext
from app.schemas.metric_review import ReviewedMetricPlan, ReviewedMetricResult
from app.schemas.models import NetworkReport, QueryPlan, RagResult, RoutePlan, Scope, SqlResult
from app.schemas.state import NetworkState
from app.security.redaction import redact_sensitive_text
from app.semantics.catalog import CATALOG_VERSION
from app.semantics.models import MetricMatch
from app.semantics.reviewed_metrics import MetricReviewService, reviewed_metric_report
from app.storage.backends import MemoryBackend, MySQLBackend
from app.storage.metric_governance import GovernanceCapacityExceeded, GovernanceStorageUnavailable
from app.tools.sql_readonly import QueryService


def failure_report(state, status, message):
    route = state.get("route", "rag")
    return NetworkReport(
        answer_type={"rag": "knowledge", "sql": "data", "both": "diagnosis"}[route],
        status=status,
        summary=message,
        question=state.get("normalized_question", state["question"]),
        timezone=state["timezone"],
        limitations=["本次未取得完整调查结论；保存状态以响应 checkpoint_saved 字段为准。"],
    )


def build_graph(
    agent_runtime: AgentRuntime, settings: Settings, checkpointer=None, metric_reviews=None
):
    async def supervisor(state, runtime: Runtime[InvocationContext]):
        with runtime.context.trace.span("agent.supervisor") as span:
            try:
                if metric_reviews is not None and runtime.context.principal is not None:
                    named = await metric_reviews.resolve_named(
                        runtime.context.principal, state["question"], state["timezone"]
                    )
                    if named is not None:
                        span["outcome"] = named.metric_match.status
                        return {
                            "route": named.route,
                            "normalized_question": named.normalized_question,
                            "route_plan": named.model_dump(mode="json"),
                            "rag_result": None,
                            "sql_result": None,
                            "generated_sql_result": None,
                            "reviewed_metric_result": None,
                            "final_report": None,
                            "report_calls": 0,
                            "previous_sql_context": None,
                            "previous_sql_question": "",
                        }
                history = [
                    message.content
                    for message in state.get("messages", [])[:-1]
                    if message.type == "human"
                ]
                previous = (
                    RoutePlan.model_validate(state["route_plan"])
                    if state.get("route_plan")
                    else None
                )
                previous_generated = state.get("generated_sql_result") or {}
                previous_sql_context = previous_generated.get("request_context")
                if not previous_sql_context and previous and previous.query_plan:
                    previous_sql_context = {
                        key: getattr(previous.query_plan, key)
                        for key in (
                            "devices",
                            "interface",
                            "start_utc",
                            "end_utc",
                            "severity",
                            "alarm_type",
                        )
                    }
                    previous_sql_context = SqlRequestContext(
                        **previous_sql_context,
                        timezone=state["timezone"],
                        all_devices=not previous.query_plan.devices
                        and bool(
                            re.search(
                                r"全网|所有设备|全部设备|all devices",
                                previous.normalized_question,
                                re.I,
                            )
                        ),
                    ).model_dump(mode="json")
                baseline = build_route_plan(
                    state["question"],
                    settings.demo_now,
                    state["timezone"],
                    history,
                    previous if previous and previous.query_plan else None,
                )
                if (
                    previous
                    and previous.needs_clarification
                    and not previous.semantic_issues
                    and (
                        baseline.needs_clarification
                        or (
                            baseline.metric_match
                            and baseline.metric_match.status == "miss"
                            and baseline.metric_match.reason_codes == ["unknown_metric"]
                        )
                    )
                    and (state.get("final_report") or {}).get("status") == "needs_clarification"
                ):
                    old_question = previous.normalized_question
                    try:
                        new_window = resolve_window(
                            state["question"], settings.demo_now, state["timezone"]
                        )
                        if new_window[0]:
                            old_question = re.sub(
                                r"\d{4}-\d{2}-\d{2}|(?:最近|过去|last|past)\s*\d+\s*(?:小时|hours?|h)|昨天|今天|yesterday|today",
                                "",
                                old_question,
                                flags=re.I,
                            )
                    except ValueError:
                        pass
                    if re.search(r"R\d+", state["question"], re.I):
                        old_question = re.sub(r"R\d+", "", old_question, flags=re.I)
                    baseline = build_route_plan(
                        old_question + "；补充：" + state["question"],
                        settings.demo_now,
                        state["timezone"],
                        history,
                    )
                plan = await agent_runtime.plan_request(
                    state["question"],
                    settings.demo_now,
                    state["timezone"],
                    history=history,
                    previous=previous,
                    baseline=baseline,
                )
                if plan.metric_match:
                    span["outcome"] = plan.metric_match.status
                return {
                    "route": plan.route,
                    "normalized_question": plan.normalized_question,
                    "route_plan": plan.model_dump(mode="json"),
                    "rag_result": None,
                    "sql_result": None,
                    "final_report": None,
                    "report_calls": 0,
                    "generated_sql_result": None,
                    "reviewed_metric_result": None,
                    "previous_sql_context": previous_sql_context,
                    "previous_sql_question": previous_generated.get(
                        "question", previous.normalized_question if previous else ""
                    ),
                }
            except Exception as exc:
                span.update(status="error", error_type=type(exc).__name__)
                # Deliberately do not return exception text / provider URL / credentials.
                plan = RoutePlan(
                    route="rag",
                    normalized_question=state["question"],
                    needs_clarification=True,
                    clarification_question=f"路由处理未完成（{type(exc).__name__}）；请重试或检查模型配置。",
                    metric_match=MetricMatch(
                        status="error",
                        planner="llm" if settings.llm_mode == "openai" else "rule_mock",
                        catalog_version=CATALOG_VERSION,
                        reason_codes=["planning_error"],
                    ),
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
                    "generated_sql_result": None,
                    "reviewed_metric_result": None,
                    "previous_sql_context": None,
                    "previous_sql_question": "",
                }

    def select_route(state):
        if state["route_plan"].get("reviewed_metric_plan"):
            return "reviewed_metric"
        if (state["route_plan"].get("metric_match") or {}).get("status") == "miss":
            return "generated_sql" if settings.text_to_sql_enabled else "metrics_miss"
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
        payload = {}
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
                result = await agent_runtime.report(payload, scope=runtime.context.scope)
            except Exception as exc:
                span.update(status="error", error_type=type(exc).__name__)
                result = failure_report(
                    state,
                    "failed",
                    f"报告生成未完成（{type(exc).__name__}）；查询/检索证据保留在本次响应。",
                )
                if state["route"] == "rag":
                    result.generation_mode = (
                        "agentic_rag" if settings.llm_mode == "openai" else "mock_rag"
                    )
            return {
                "final_report": result.model_dump(mode="json"),
                "rag_result": payload.get("rag_result", state.get("rag_result")),
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

    def metrics_miss(state):
        match = state["route_plan"]["metric_match"]
        reasons = [issue["message"] for issue in state["route_plan"].get("semantic_issues", [])]
        report = failure_report(state, "not_matched", "指标查询层未命中：" + "；".join(reasons))
        report.limitations = [
            "本次没有执行指标查询，也未用其他指标替代所需数据。",
            "SQL 示例缓存层按配置跳过；第三层 Text-to-SQL 当前已关闭，本次停止于明确的未命中状态。",
            "指标未命中不等同于已查询但没有数据。",
        ]
        report.next_checks = match.get("unmatched_requests", [])
        return {
            "final_report": report.model_dump(mode="json"),
            "report_calls": 0,
            "messages": [AIMessage(content=report.summary, id=f"answer:{state['request_id']}")],
        }

    async def run_generated_sql(state, runtime: Runtime[InvocationContext]):
        with runtime.context.trace.span("agent.sql_fallback") as span:
            try:
                candidate = state["route_plan"].get("query_plan")
                previous = state.get("previous_sql_context")
                if candidate:
                    previous = {
                        key: candidate.get(key)
                        for key in (
                            "devices",
                            "interface",
                            "start_utc",
                            "end_utc",
                            "severity",
                            "alarm_type",
                        )
                    }
                    previous["timezone"] = state["timezone"]
                    previous["all_devices"] = not candidate.get("devices") and bool(
                        re.search(r"全网|所有设备|全部设备|all devices", state["question"], re.I)
                    )
                result = await agent_runtime.generated_sql(
                    state["question"],
                    runtime.context.scope,
                    state["timezone"],
                    runtime.context.trace,
                    previous=SqlRequestContext.model_validate(previous) if previous else None,
                    metric_match=RoutePlan.model_validate(state["route_plan"]).metric_match,
                    previous_question=state.get("previous_sql_question", ""),
                )
                span["outcome"] = result.status
            except Exception as exc:
                span.update(status="error", error_type=type(exc).__name__)
                result = GeneratedSqlResult(
                    status="timeout" if isinstance(exc, TimeoutError) else "error",
                    planner="mock" if settings.llm_mode == "mock" else "llm",
                    question=state["question"],
                    reason_codes=["sql_generation_failed"],
                    missing_evidence=[
                        f"模型 SQL 处理未完成（{type(exc).__name__}），未回退为伪造成功。"
                    ],
                )
        with runtime.context.trace.span(
            "agent.report" if result.queries else "agent.sql_resolution"
        ):
            report = generated_sql_report(result, state["question"], state["timezone"])
        return {
            "generated_sql_result": result.model_dump(mode="json"),
            "final_report": report.model_dump(mode="json"),
            "report_calls": 1 if result.queries else 0,
            "messages": [AIMessage(content=report.summary, id=f"answer:{state['request_id']}")],
        }

    async def run_reviewed_metric(state, runtime: Runtime[InvocationContext]):
        with runtime.context.trace.span("tool.query_reviewed_metric") as span:
            try:
                result = await metric_reviews.execute(
                    runtime.context.principal,
                    ReviewedMetricPlan.model_validate(state["route_plan"]["reviewed_metric_plan"]),
                )
                span["outcome"] = result.status
            except Exception as exc:
                span.update(status="error", error_type=type(exc).__name__)
                result = ReviewedMetricResult(
                    status="error",
                    missing_evidence=["正式指标查询或存储未完成，请检查依赖后重试。"],
                )
        report = reviewed_metric_report(result, state["question"], state["timezone"])
        return {
            "reviewed_metric_result": result.model_dump(mode="json"),
            "final_report": report.model_dump(mode="json"),
            "report_calls": 1 if result.queries else 0,
            "messages": [AIMessage(content=report.summary, id=f"answer:{state['request_id']}")],
        }

    builder = StateGraph(NetworkState, context_schema=InvocationContext)
    builder.add_node("supervisor", supervisor)
    builder.add_node("clarify", clarify)
    builder.add_node("metrics_miss", metrics_miss)
    builder.add_node("generated_sql", run_generated_sql)
    builder.add_node("reviewed_metric", run_reviewed_metric)
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
        "supervisor",
        select_route,
        [
            "clarify",
            "metrics_miss",
            "generated_sql",
            "reviewed_metric",
            "rag_only",
            "sql_only",
            "dispatch_both",
        ],
    )
    builder.add_edge("clarify", END)
    builder.add_edge("metrics_miss", END)
    builder.add_edge("generated_sql", END)
    builder.add_edge("reviewed_metric", END)
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
        self.request_slots = asyncio.Semaphore(self.settings.max_concurrent_requests)
        self.backend = (
            MemoryBackend(self.settings)
            if self.settings.data_backend == "mock"
            else MySQLBackend(self.settings)
        )
        self.query_service = QueryService(self.backend, self.settings)
        self.metric_reviews = (
            MetricReviewService(sessions, self.query_service, self.settings)
            if sessions is not None
            else None
        )
        self.governance = (
            GovernanceFeedbackService(sessions, self.metric_reviews)
            if sessions is not None
            else None
        )
        embedding = (
            OpenAIEmbedding(self.settings) if self.settings.embedding_mode == "openai" else None
        )
        self.retriever = HybridRetriever(
            load_documents(self.settings.knowledge_dir, self.settings), self.settings, embedding
        )
        self.runtime = AgentRuntime(self.settings, self.retriever, self.query_service)
        self.graph = build_graph(self.runtime, self.settings, checkpointer, self.metric_reviews)
        self.stateless_graph = (
            build_graph(self.runtime, self.settings, metric_reviews=self.metric_reviews)
            if checkpointer
            else self.graph
        )

    async def analyze(
        self,
        question: str,
        timezone: str = "Asia/Shanghai",
        scope: Scope | None = None,
        history: list[str] | None = None,
    ):
        question = redact_sensitive_text(question)
        history = [redact_sensitive_text(item) for item in history] if history else None
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
            "evidence": {
                "rag": state.get("rag_result"),
                "sql": state.get("sql_result"),
                **(
                    {"generated_sql": state["generated_sql_result"]}
                    if state.get("generated_sql_result")
                    else {}
                ),
                **(
                    {"reviewed_metric": state["reviewed_metric_result"]}
                    if state.get("reviewed_metric_result")
                    else {}
                ),
            },
            "query_path": "reviewed_metric"
            if state.get("reviewed_metric_result")
            else "text_to_sql"
            if state.get("generated_sql_result")
            else "rag"
            if state.get("route") == "rag"
            else "metrics",
            "trace": trace.snapshot(),
            "report_calls": state["report_calls"],
            "persistence_enabled": session_id is not None
            and self.settings.persistence_backend == "postgres",
            "checkpoint_saved": session_id is not None,
            "checkpoint_backend": self.settings.persistence_backend if session_id else "none",
            "session_id": session_id,
            "metric_match": state.get("route_plan", {}).get("metric_match"),
            "query_plan": state.get("route_plan", {}).get("query_plan"),
            "reviewed_metric_plan": state.get("route_plan", {}).get("reviewed_metric_plan"),
            "clarification": {
                "question": state["generated_sql_result"].get("clarification_question"),
                "semantic_issues": [],
            }
            if (state.get("generated_sql_result") or {}).get("status") == "clarify"
            else {
                "question": "；".join(state["reviewed_metric_result"].get("missing_evidence", [])),
                "semantic_issues": [],
            }
            if (state.get("reviewed_metric_result") or {}).get("status") == "clarify"
            else {
                "question": state["route_plan"].get("clarification_question"),
                "semantic_issues": state["route_plan"].get("semantic_issues", []),
            }
            if state.get("route_plan", {}).get("needs_clarification")
            else None,
        }

    async def resolve_metrics(self, question, timezone="Asia/Shanghai", principal=None):
        """Independent first-layer endpoint: planning only, no SQL/RAG execution."""
        question = redact_sensitive_text(question)
        trace = RequestTrace(f"trace_{uuid4().hex}")
        async with self.request_slot():
            token = active_trace.set(trace)
            try:
                plan = (
                    await self.metric_reviews.resolve_named(principal, question, timezone)
                    if self.metric_reviews and principal
                    else None
                )
                if plan is None:
                    plan = await self.runtime.plan_request(
                        question, self.settings.demo_now, timezone
                    )
            finally:
                active_trace.reset(token)
        return {
            "route": plan.route,
            "metric_match": plan.metric_match.model_dump(mode="json"),
            "query_plan": plan.query_plan.model_dump(mode="json") if plan.query_plan else None,
            "reviewed_metric_plan": plan.reviewed_metric_plan.model_dump(mode="json")
            if plan.reviewed_metric_plan
            else None,
            "clarification": {
                "question": plan.clarification_question,
                "semantic_issues": [i.model_dump(mode="json") for i in plan.semantic_issues],
            }
            if plan.needs_clarification
            else None,
            "trace": trace.snapshot(),
        }

    @staticmethod
    def thread_config(principal, session_id):
        return {
            "configurable": {
                "thread_id": f"{principal.scope.tenant_id}:{principal.user_id}:{session_id}"
            }
        }

    @asynccontextmanager
    async def request_slot(self):
        from app.storage.sessions import RequestCapacity

        try:
            await asyncio.wait_for(self.request_slots.acquire(), timeout=1)
        except TimeoutError:
            raise RequestCapacity from None
        try:
            yield
        finally:
            self.request_slots.release()

    async def chat(self, principal, session_id, question, timezone):
        async with self.request_slot():
            return await self._chat(principal, session_id, question, timezone)

    async def _chat(self, principal, session_id, question, timezone):
        question = redact_sensitive_text(question)
        if self.sessions is None:
            raise RuntimeError("Session repository not configured")
        async with self.sessions.lock(session_id, principal):
            request_id = f"req_{uuid4().hex}"
            trace = RequestTrace(f"trace_{uuid4().hex}")
            await self.sessions.start_request(request_id, session_id, principal, question, timezone)
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
                        context=InvocationContext(principal.scope, trace, principal),
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
            return await self.decorate_response(principal, response, capture=True)

    async def resume(self, principal, session_id):
        async with self.request_slot():
            return await self._resume(principal, session_id)

    async def _resume(self, principal, session_id):
        from app.storage.sessions import SessionMissing

        async with self.sessions.lock(session_id, principal):
            config = self.thread_config(principal, session_id)
            snapshot = await self.graph.aget_state(config)
            history = await self.sessions.messages(session_id, principal, limit=1)
            latest = history[-1] if history else None
            rerun_input = None
            if (
                latest
                and (
                    not snapshot.values or snapshot.values.get("request_id") != latest["request_id"]
                )
                and (
                    latest["status"] == "running"
                    or (latest.get("response") or {}).get("interrupted")
                )
            ):
                rerun_input = {
                    "question": latest["message"],
                    "timezone": latest["timezone"],
                    "request_id": latest["request_id"],
                    "messages": [
                        {
                            "role": "user",
                            "content": latest["message"],
                            "id": f"question:{latest['request_id']}",
                        }
                    ],
                }
            if not snapshot.values and rerun_input is None:
                raise SessionMissing
            trace = RequestTrace(f"trace_{uuid4().hex}")
            token = active_trace.set(trace)
            try:
                state = (
                    await asyncio.wait_for(
                        self.graph.ainvoke(
                            rerun_input,
                            config=config,
                            context=InvocationContext(principal.scope, trace, principal),
                            durability="sync",
                        ),
                        self.settings.request_timeout_seconds,
                    )
                    if snapshot.next or rerun_input is not None
                    else snapshot.values
                )
                response = self.response(state, trace, session_id)
                response["restored"] = True
                await self.sessions.finish_request(state["request_id"], response)
                return await self.decorate_response(principal, response, capture=True)
            finally:
                active_trace.reset(token)

    async def delete_session(self, principal, session_id):
        async with self.sessions.lock(session_id, principal):
            await self.graph.checkpointer.adelete_thread(
                self.thread_config(principal, session_id)["configurable"]["thread_id"]
            )
            await self.sessions.delete(session_id, principal)

    async def decorate_response(self, principal, response, *, capture=False, document=None):
        """Business response is already saved; feedback failures remain explicit/retryable."""
        response = dict(response)
        try:
            if document is None and not capture:
                document = await self.metric_reviews.store.read(principal)
            feedback = (
                await self.governance.capture(principal, response["request_id"])
                if capture
                else await self.governance.describe(
                    principal, response["request_id"], document=document
                )
            )
            response = await self.metric_reviews.decorate(principal, response, document=document)
            response["governance_feedback"] = feedback
        except (GovernanceStorageUnavailable, GovernanceCapacityExceeded) as exc:
            response["governance_feedback"] = {
                "capture_status": "pending",
                "case_ids": [],
                "reason": "storage_unavailable"
                if isinstance(exc, GovernanceStorageUnavailable)
                else "capacity",
                "message": "本次调查记录已保存，治理反馈尚未归档；可在治理页补收。",
            }
            response["query_reviews_unavailable"] = True
        return response

    async def decorate_history(self, principal, rows):
        rows = deepcopy(rows)
        try:
            document = await self.metric_reviews.store.read(principal)
        except (GovernanceStorageUnavailable, GovernanceCapacityExceeded):
            for row in rows:
                if row.get("response"):
                    row["response"]["governance_feedback"] = {
                        "capture_status": "pending",
                        "case_ids": [],
                        "reason": "storage_unavailable",
                    }
                    row["response"]["query_reviews_unavailable"] = True
            return rows
        for row in rows:
            if row.get("response"):
                row["response"] = await self.decorate_response(
                    principal, row["response"], document=document
                )
        return rows

    def run(self, question, **kwargs):
        return asyncio.run(self.analyze(question, **kwargs))

    def close(self):
        self.retriever.close()
        if hasattr(self.backend, "close"):
            self.backend.close()
