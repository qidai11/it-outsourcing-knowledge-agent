FROM ghcr.io/astral-sh/uv:0.12.13 AS uv
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH"

COPY --from=uv /uv /uvx /bin/
WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY migrations ./migrations
COPY alembic.ini ./
COPY scripts ./scripts
RUN uv sync --frozen --no-dev

RUN useradd --create-home --uid 10001 app \
    && mkdir -p /var/lib/project-agent/data \
    && chown -R app:app /app /var/lib/project-agent
USER app

CMD ["uvicorn", "project_agent.main:app", "--host", "0.0.0.0", "--port", "8000"]
