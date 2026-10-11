from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.config import Settings
from app.graph.workflow import WorkflowService
from app.schemas.models import AnalyzeRequest, Scope


def create_app(settings: Settings | None = None):
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app):
        service = WorkflowService(settings)
        app.state.service = service
        try:
            yield
        finally:
            service.close()

    api = FastAPI(
        title="Network AIOps · Steps 1–8",
        version="0.1.0",
        lifespan=lifespan,
        description="本地开发验证 API：固定服务端 demo 权限、无会话/Checkpoint 持久化，非生产认证入口。",
    )

    @api.get("/health")
    @api.get("/api/v1/health")
    def health():
        service = api.state.service
        try:
            service.query_service.execute(
                "SELECT hostname FROM v_device_status LIMIT 1", {}, Scope()
            )
            ready = bool(service.retriever.chunks)
        except Exception:
            ready = False
        return JSONResponse(
            status_code=200 if ready else 503,
            content={
                "status": "ok" if ready else "degraded",
                "milestone": 8,
                "persistence_enabled": False,
                "database": settings.data_backend,
                "llm": settings.llm_mode,
                "llm_readiness": "offline_mock"
                if settings.llm_mode == "mock"
                else "configured_not_probed",
                "embedding": settings.embedding_mode,
                "data_kind": "demo",
                "demo_now": settings.demo_now.isoformat(),
            },
        )

    @api.post("/api/v1/demo/analyze")
    async def analyze(request: AnalyzeRequest):
        # Public callers cannot specify scope, session ownership or identity.
        return await api.state.service.analyze(request.message, request.timezone, Scope())

    return api


app = create_app()
