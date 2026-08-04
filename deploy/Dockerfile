# syntax=docker/dockerfile:1.7
FROM node:22-alpine AS frontend
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim AS runtime
COPY --from=ghcr.io/astral-sh/uv:0.11.26 /uv /uvx /bin/
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

COPY pyproject.toml uv.lock README.md ./
COPY src/ ./src/
RUN uv sync --frozen --no-dev

COPY alembic.ini ./
COPY migrations/ ./migrations/
COPY --from=frontend /build/frontend/dist ./frontend/dist/
COPY deploy/entrypoint.sh /usr/local/bin/forgejo-mcp-entrypoint

RUN groupadd --system app && useradd --system --gid app --home /app app \
    && chown -R app:app /app \
    && chmod 0755 /usr/local/bin/forgejo-mcp-entrypoint

ENTRYPOINT ["forgejo-mcp-entrypoint"]
EXPOSE 8000
CMD ["uvicorn", "forgejo_mcp.main:app", "--host", "0.0.0.0", "--port", "8000"]
