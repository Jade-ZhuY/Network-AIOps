import asyncio
from contextlib import AsyncExitStack, asynccontextmanager
from copy import deepcopy
from typing import Annotated

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from langgraph.checkpoint.memory import InMemorySaver

from app.config import ROOT, Settings
from app.graph.workflow import WorkflowService
from app.rag.management import KnowledgeManager
from app.schemas.governance import CaseKind, CaseStatus, CaseUpdate, CaseVerify
from app.schemas.metric_review import PublishMetricInput, QueryReviewInput
from app.schemas.models import AnalyzeRequest, ChatRequest, Scope, SessionCreate
from app.security.auth import Principal, admin_principal, current_principal
from app.semantics.catalog import public_catalog
from app.storage.checkpoint import postgres_resources
from app.storage.metric_governance import GovernanceCapacityExceeded, GovernanceStorageUnavailable
from app.storage.sessions import (
    MemorySessions,
    PostgresSessions,
    RequestCapacity,
    SessionBusy,
    SessionMissing,
)

User = Annotated[Principal, Depends(current_principal)]
Admin = Annotated[Principal, Depends(admin_principal)]
FRONTEND_DIST = ROOT / "app" / "web" / "dist"


def create_app(settings: Settings | None = None):
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app):
        async with AsyncExitStack() as stack:
            saver, sessions = None, None
            if settings.persistence_backend == "postgres":
                pool, saver = await stack.enter_async_context(postgres_resources(settings))
                sessions = PostgresSessions(pool)
            elif settings.persistence_backend == "memory":
                saver, sessions = InMemorySaver(), MemorySessions()
            service = WorkflowService(settings, saver, sessions)
            stack.callback(service.close)
            app.state.service = service
            app.state.settings = settings
            if sessions is not None:
                app.state.knowledge = KnowledgeManager(service, sessions, settings)
                await app.state.knowledge.rebuild()
            yield

    api = FastAPI(
        title="Network AIOps",
        version="0.2.0",
        lifespan=lifespan,
        description="四 Agent 网络运维助理：服务端权限、只读查询、证据报告、持久会话与追踪。",
    )

    @api.middleware("http")
    async def security_headers(request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        if request.url.path == "/" or request.url.path.startswith("/static/"):
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'"
            )
        return response

    # React assets are built separately; never serve TypeScript source or credentials.
    # Hash routing keeps direct links compatible with both FastAPI and a future Java host.
    frontend_dist = FRONTEND_DIST
    if frontend_dist.is_dir():
        api.mount("/static", StaticFiles(directory=frontend_dist), name="static")

    @api.get("/", include_in_schema=False)
    async def index():
        entry = frontend_dist / "index.html"
        if entry.is_file():
            return FileResponse(entry, headers={"Cache-Control": "no-cache"})
        return JSONResponse(
            status_code=503,
            content={
                "detail": "frontend_build_required",
                "message": "React 工作台尚未构建。请在 frontend 目录执行 npm ci 和 npm run build，然后重启后端；或使用 npm run dev 开发。",
            },
        )

    @api.get("/health")
    @api.get("/api/v1/health")
    async def health():
        service = api.state.service
        try:
            await asyncio.to_thread(
                service.query_service.execute,
                "SELECT hostname FROM v_device_status LIMIT 1",
                {},
                Scope(),
            )
            ready = bool(service.retriever.children)
            await asyncio.to_thread(service.retriever.healthcheck)
            if settings.persistence_backend == "postgres":
                async with service.sessions.pool.connection() as connection:
                    await connection.execute("SELECT 1 FROM aiops_sessions LIMIT 1")
                    await connection.execute("SELECT 1 FROM aiops_metric_governance LIMIT 1")
        except Exception:
            ready = False
        return JSONResponse(
            status_code=200 if ready else 503,
            content={
                "status": "ok" if ready else "degraded",
                "milestone": 11 if settings.persistence_backend != "none" else 8,
                "persistence_enabled": settings.persistence_backend == "postgres",
                "checkpoint": settings.persistence_backend,
                "database": settings.data_backend,
                "llm": settings.llm_mode,
                "model": settings.llm_model
                if settings.llm_mode == "openai"
                else "deterministic-mock",
                "llm_readiness": "offline_mock"
                if settings.llm_mode == "mock"
                else "verified_this_process"
                if service.runtime.last_model_ok_at
                else "configured_not_probed",
                "embedding": settings.embedding_mode,
                "document_parser": "mineru",
                "document_parser_version": settings.mineru_expected_version,
                "vector_backend": settings.rag_vector_backend,
                "vector_collection": settings.milvus_collection
                if settings.rag_vector_backend == "milvus"
                else None,
                "data_kind": "demo",
                "text_to_sql_enabled": settings.text_to_sql_enabled,
                "metric_review_storage": settings.persistence_backend,
                "demo_now": settings.demo_now.isoformat(),
            },
        )

    if settings.enable_demo_api and settings.environment != "production":

        @api.post("/api/v1/demo/analyze")
        async def analyze(request: AnalyzeRequest):
            return await api.state.service.analyze(request.message, request.timezone, Scope())

    @api.exception_handler(SessionMissing)
    async def session_missing(request, exc):
        return JSONResponse(status_code=404, content={"detail": "Session or request not found"})

    @api.exception_handler(SessionBusy)
    async def session_busy(request, exc):
        return JSONResponse(
            status_code=409,
            content={"detail": "Session has an active request; retry after completion"},
        )

    @api.exception_handler(RequestCapacity)
    async def capacity(request, exc):
        return JSONResponse(
            status_code=429,
            content={"detail": "Investigation concurrency limit reached"},
            headers={"Retry-After": "2"},
        )

    @api.exception_handler(GovernanceStorageUnavailable)
    async def governance_unavailable(request, exc):
        return JSONResponse(
            status_code=503,
            content={"detail": "指标审核存储未就绪，请检查 PostgreSQL 连接并执行显式迁移。"},
        )

    @api.exception_handler(GovernanceCapacityExceeded)
    async def governance_capacity(request, exc):
        return JSONResponse(
            status_code=409, content={"detail": "当前身份的治理记录已达容量上限，需要归档后继续。"}
        )

    @api.get("/api/v1/metrics")
    async def metric_definitions(principal: User):
        """Public metric definitions only; no business rows, credentials or base tables."""
        catalog = public_catalog()
        catalog["capabilities"]["fallback_connected"] = settings.text_to_sql_enabled
        if api.state.service.metric_reviews:
            catalog["reviewed_metrics"] = await api.state.service.metric_reviews.list_metrics(
                principal
            )
        return catalog

    @api.post("/api/v1/metrics/resolve")
    async def resolve_metrics(request: AnalyzeRequest, principal: User):
        try:
            return await api.state.service.resolve_metrics(
                request.message, request.timezone, principal
            )
        except RequestCapacity:
            raise
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail={"code": "metric_planning_failed", "error_type": type(exc).__name__},
            ) from None

    if settings.persistence_backend != "none":

        @api.get("/api/v1/me")
        async def me(principal: User):
            return {
                "user_id": principal.user_id,
                "role": principal.role,
                "tenant_id": principal.scope.tenant_id,
                "scope": principal.scope.model_dump(mode="json"),
            }

        @api.post("/api/v1/sessions", status_code=201)
        async def create_session(request: SessionCreate, principal: User):
            return await api.state.service.sessions.create(
                principal, request.title, request.timezone
            )

        @api.get("/api/v1/sessions")
        async def list_sessions(principal: User, limit: int = Query(50, ge=1, le=200)):
            return {"sessions": await api.state.service.sessions.list(principal, limit)}

        @api.get("/api/v1/sessions/{session_id}")
        async def get_session(session_id: str, principal: User):
            return await api.state.service.sessions.get(session_id, principal)

        @api.get("/api/v1/sessions/{session_id}/messages")
        async def messages(
            session_id: str,
            principal: User,
            limit: int = Query(200, ge=1, le=200),
        ):
            rows = await api.state.service.sessions.messages(session_id, principal, limit)
            rows = await api.state.service.decorate_history(principal, rows)
            return {"messages": rows}

        @api.post("/api/v1/chat")
        async def chat(request: ChatRequest, principal: User):
            try:
                return await api.state.service.chat(
                    principal, request.session_id, request.message, request.timezone
                )
            except (SessionMissing, SessionBusy, RequestCapacity):
                raise
            except Exception as exc:
                # Persistence failure never returns a fake successful saved response.
                raise HTTPException(
                    status_code=503,
                    detail={
                        "error": "execution_or_storage_unavailable",
                        "error_type": type(exc).__name__,
                    },
                ) from None

        @api.post("/api/v1/sessions/{session_id}/resume")
        async def resume(session_id: str, principal: User):
            try:
                return await api.state.service.resume(principal, session_id)
            except (SessionMissing, SessionBusy, RequestCapacity):
                raise
            except Exception as exc:
                raise HTTPException(
                    status_code=503,
                    detail={
                        "error": "resume_or_storage_unavailable",
                        "error_type": type(exc).__name__,
                    },
                ) from None

        @api.delete("/api/v1/sessions/{session_id}", status_code=204)
        async def delete_session(session_id: str, principal: User):
            await api.state.service.delete_session(principal, session_id)

        @api.get("/api/v1/requests/{request_id}")
        async def request_detail(request_id: str, principal: User):
            row = deepcopy(await api.state.service.sessions.request(request_id, principal))
            if row.get("response"):
                row["response"] = await api.state.service.decorate_response(
                    principal, row["response"]
                )
            return row

        @api.get("/api/v1/requests/{request_id}/queries/{query_id}/review")
        async def query_review(request_id: str, query_id: str, principal: User):
            return await api.state.service.metric_reviews.get_review(
                principal, request_id, query_id
            )

        @api.put("/api/v1/requests/{request_id}/queries/{query_id}/review")
        async def review_query(
            request_id: str, query_id: str, request: QueryReviewInput, principal: User
        ):
            return await api.state.service.metric_reviews.review(
                principal, request_id, query_id, request
            )

        @api.get("/api/v1/requests/{request_id}/queries/{query_id}/metric-candidate")
        async def metric_candidate(request_id: str, query_id: str, principal: User):
            return await api.state.service.metric_reviews.candidate(principal, request_id, query_id)

        @api.post("/api/v1/requests/{request_id}/queries/{query_id}/metric", status_code=201)
        async def publish_query_metric(
            request_id: str, query_id: str, request: PublishMetricInput, principal: User
        ):
            return await api.state.service.metric_reviews.publish(
                principal, request_id, query_id, request
            )

        @api.get("/api/v1/metrics/reviewed")
        async def reviewed_metrics(principal: User, include_inactive: bool = False):
            return {
                "metrics": await api.state.service.metric_reviews.list_metrics(
                    principal, include_inactive=include_inactive
                ),
                "storage": settings.persistence_backend,
                "durable": settings.persistence_backend == "postgres",
            }

        @api.delete("/api/v1/metrics/reviewed/{metric_id}")
        async def withdraw_metric(metric_id: str, principal: User, version: int = Query(ge=1)):
            return await api.state.service.metric_reviews.withdraw(principal, metric_id, version)

        @api.get("/api/v1/governance/cases")
        async def governance_cases(
            principal: User,
            status: CaseStatus | None = None,
            kind: CaseKind | None = None,
            offset: int = Query(0, ge=0, le=10000),
            limit: int = Query(30, ge=1, le=100),
        ):
            result = await api.state.service.governance.list(principal, status, kind, offset, limit)
            return {
                **result,
                "storage": settings.persistence_backend,
                "durable": settings.persistence_backend == "postgres",
            }

        @api.get("/api/v1/governance/cases/{case_id}")
        async def governance_case(case_id: str, principal: User):
            return await api.state.service.governance.get(principal, case_id)

        @api.patch("/api/v1/governance/cases/{case_id}")
        async def update_governance_case(case_id: str, request: CaseUpdate, principal: User):
            return await api.state.service.governance.update(principal, case_id, request)

        @api.post("/api/v1/governance/cases/{case_id}/verify")
        async def verify_governance_case(case_id: str, request: CaseVerify, principal: User):
            async with api.state.service.request_slot():
                return await api.state.service.governance.verify(principal, case_id, request)

        @api.post("/api/v1/governance/capture/{request_id}")
        async def capture_governance_request(request_id: str, principal: User):
            return await api.state.service.governance.capture(principal, request_id)

        @api.post("/api/v1/governance/collect")
        async def collect_governance(principal: User, limit: int = Query(20, ge=1, le=50)):
            async with api.state.service.request_slot():
                return await api.state.service.governance.collect_recent(principal, limit)

        @api.get("/api/v1/admin/audit")
        async def audit(principal: Admin, limit: int = Query(50, ge=1, le=200)):
            return {"requests": await api.state.service.sessions.audit(principal, limit)}

        @api.get("/api/v1/knowledge/documents")
        async def documents(principal: User):
            return {"documents": await api.state.knowledge.list(principal)}

        @api.get("/api/v1/knowledge/documents/{doc_id}")
        async def document(doc_id: str, principal: User):
            return await api.state.knowledge.get(doc_id, principal)

        @api.post("/api/v1/knowledge/documents", status_code=201)
        async def upload(
            principal: Admin,
            file: Annotated[UploadFile, File()],
            title: Annotated[str, Form(max_length=100)] = "",
        ):
            content = await file.read(settings.upload_max_bytes + 1)
            return await api.state.knowledge.upload(
                file.filename or "document", title, content, principal
            )

        @api.post("/api/v1/knowledge/reindex")
        async def reindex(principal: Admin):
            await api.state.knowledge.rebuild()
            return {"status": "ready"}

        @api.delete("/api/v1/knowledge/documents/{doc_id}", status_code=204)
        async def delete_document(doc_id: str, principal: Admin):
            await api.state.knowledge.remove(doc_id, principal)

    return api


app = create_app()
