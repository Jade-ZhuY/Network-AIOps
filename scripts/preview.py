"""Disposable localhost UI fixture. Never uses real API keys or durable data."""

import asyncio

import uvicorn

from app.config import Settings
from app.main import create_app

if __name__ == "__main__":
    settings = Settings(
        _env_file=None,
        environment="test",
        llm_mode="mock",
        data_backend="mock",
        persistence_backend="memory",
        api_auth_token="preview-engineer-token",
        api_admin_token="preview-admin-token",
        enable_demo_api=False,
    )
    app = create_app(settings)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=8081))
    with asyncio.Runner() as runner:
        runner.run(server.serve())
