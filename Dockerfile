FROM oven/bun:1 AS frontend-builder

WORKDIR /app/web-ui/frontend
COPY web-ui/frontend/package.json web-ui/frontend/bun.lock ./
RUN bun install --frozen-lockfile
COPY web-ui/frontend/ ./
RUN bun run build

FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS backend-builder

WORKDIR /app
ENV UV_PROJECT_ENVIRONMENT=/opt/venv

COPY pyproject.toml uv.lock README.md ./
COPY b2t ./b2t
COPY web-ui/backend ./web-ui/backend
RUN uv sync --frozen --no-dev

FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PATH=/opt/venv/bin:${PATH} \
    FRONTEND_PORT=6010 \
    BACKEND_HOST=127.0.0.1 \
    BACKEND_PORT=8000 \
    B2T_CONFIG=/app/config.toml

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        nginx \
        ffmpeg \
        gettext-base \
        pandoc \
        fontconfig \
        fonts-noto-cjk \
        fonts-wqy-zenhei \
    && rm -rf /var/lib/apt/lists/* \
    && rm -f /etc/nginx/sites-enabled/default /etc/nginx/conf.d/default.conf \
    && fc-cache -f

COPY --from=backend-builder /opt/venv /opt/venv
COPY --from=frontend-builder /app/web-ui/frontend/dist /usr/share/nginx/html

COPY b2t ./b2t
COPY web-ui/backend ./web-ui/backend
COPY config.toml.example ./config.toml.example
COPY docker/nginx.conf.template /etc/nginx/templates/default.conf.template
COPY docker/entrypoint.sh /entrypoint.sh

RUN chmod +x /entrypoint.sh

VOLUME ["/app/transcriptions"]
EXPOSE 6010

CMD ["/entrypoint.sh"]
