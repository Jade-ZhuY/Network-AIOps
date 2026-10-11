FROM ghcr.io/astral-sh/uv:0.12.7 AS uv
FROM python:3.12-slim
COPY --from=uv /uv /uvx /bin/
WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project
COPY app ./app
COPY data ./data
COPY scripts ./scripts
RUN useradd --create-home --uid 10001 appuser && mkdir -p /app/data/uploads && chown appuser:appuser /app/data/uploads
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
USER appuser
EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
