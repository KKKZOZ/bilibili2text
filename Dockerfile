FROM oven/bun:1 AS frontend-build

WORKDIR /src/web-ui/frontend

COPY web-ui/frontend/package.json web-ui/frontend/bun.lock ./
RUN bun install --frozen-lockfile

COPY web-ui/frontend/ ./
RUN bun run build


FROM python:3.12-slim AS backend

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates ffmpeg pandoc \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.7.19 /uv /uvx /usr/local/bin/

WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
COPY b2t/ ./b2t/
RUN uv sync --frozen --no-dev --extra web
RUN uv run playwright install --with-deps chromium

COPY web-ui/ ./web-ui/

RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app /ms-playwright

USER appuser

EXPOSE 8000

CMD ["uv", "run", "--no-sync", "uvicorn", "backend.main:app", "--app-dir", "web-ui", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]


FROM nginx:alpine AS frontend

ENV FRONTEND_PORT=80 \
    BACKEND_HOST=backend \
    BACKEND_PORT=8000

COPY --from=frontend-build /src/web-ui/frontend/dist/ /usr/share/nginx/html/
COPY docker/nginx.compose.conf.template /etc/nginx/templates/default.conf.template

EXPOSE 80
