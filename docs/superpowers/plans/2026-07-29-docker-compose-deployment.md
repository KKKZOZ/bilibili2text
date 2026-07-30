# Docker Compose 部署实施计划

> **面向智能体执行者：** 必须使用子技能 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans`，逐任务实施本计划；步骤使用复选框（`- [ ]`）记录进度。

**Goal:** 为 Vue/FastAPI 应用提供一条命令可启动、持久化本地状态并继续使用阿里云 OSS 的 Docker Compose 部署方案。

**Architecture:** 一个多阶段 `Dockerfile` 使用 `backend` 与 `frontend` target 分别产出 Python/Uvicorn 和 Nginx 镜像。Compose 只暴露 Nginx；Nginx 将同源 `/api/` 流量代理到内部 `backend:8000`，后端经绑定挂载读取配置、写入本地状态。

**Tech Stack:** Docker BuildKit、Docker Compose、Python 3.12、uv、Bun、Vue/Vite、FastAPI/Uvicorn、Nginx、Playwright Chromium、ffmpeg、pandoc。

## Global Constraints

- 不新增 MinIO、数据库服务、HTTPS 网关或镜像发布流程；对象存储继续使用 `config.toml` 中的阿里云 OSS 配置。
- 后端镜像必须包含 Python 3.12、`ffmpeg`、`pandoc` 和 Playwright Chromium。
- `config.toml`、`summary_presets.toml`、`context.toml` 必须只读挂载；API 密钥不得写入镜像或 Git。
- `transcriptions`、`db_data`、`chroma_data` 必须可写绑定挂载；`docker compose down` 不得删除这些目录。
- 后端非 root 运行，Compose 默认 UID/GID 是 `1000:1000`，可用 `B2T_UID` 和 `B2T_GID` 覆盖。
- 后端只运行一个 Uvicorn worker；健康检查固定访问 `GET /api/health`，前端等待 backend 健康后启动。
- 后端或测试文件变化后运行 `uv run ruff check` 与 `uv run ruff format`。本次不改动前端源码，无需 `bun run format`。

---

## 文件结构

| 文件 | 责任 |
| --- | --- |
| `Dockerfile` | 前端静态资源构建，以及后端和前端两个镜像 target。 |
| `docker/compose-nginx.conf` | Compose 专用 Nginx 配置：监听 `80`，代理到 `backend:8000`。 |
| `docker-compose.yml` | 服务编排、健康检查、端口和六项绑定挂载。 |
| `docker-compose.env.example` | 可提交的环境变量模板，用户复制为 `.env`。 |
| `tests/test_docker_deployment.py` | 不依赖 Docker 守护进程的部署契约测试。 |
| `.dockerignore`、`README.md` | 构建上下文安全边界和完整运维说明。 |

### Task 1: 建立 Docker 部署契约测试

**Files:**

- Create: `tests/test_docker_deployment.py`

**Interfaces:**

- Consumes: 仓库根目录的 `Dockerfile`、`docker-compose.yml`、`docker/compose-nginx.conf`。
- Produces: 四个 `pytest` 用例，锁定镜像 target、代理上游、健康依赖和六项挂载。

- [ ] **Step 1: 写入失败的契约测试**

```python
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_project_file(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_dockerfile_exposes_runtime_targets() -> None:
    dockerfile = read_project_file("Dockerfile")
    assert "AS backend" in dockerfile
    assert "AS frontend" in dockerfile
    assert "python -m playwright install --with-deps chromium" in dockerfile
    assert "USER b2t" in dockerfile


def test_compose_persists_configuration_and_state() -> None:
    compose = read_project_file("docker-compose.yml")
    for fragment in (
        "${B2T_CONFIG_PATH:-./config.toml}:/app/config.toml:ro",
        "${B2T_SUMMARY_PRESETS_PATH:-./summary_presets.toml}:/app/summary_presets.toml:ro",
        "${B2T_CONTEXT_PATH:-./context.toml}:/app/context.toml:ro",
        "${B2T_TRANSCRIPTIONS_DIR:-./transcriptions}:/app/transcriptions",
        "${B2T_DB_DIR:-./db_data}:/app/db_data",
        "${B2T_CHROMA_DIR:-./chroma_data}:/app/chroma_data",
    ):
        assert fragment in compose


def test_compose_uses_internal_health_gated_backend() -> None:
    compose = read_project_file("docker-compose.yml")
    assert "http://127.0.0.1:8000/api/health" in compose
    assert "condition: service_healthy" in compose
    assert "${B2T_FRONTEND_PORT:-6010}:80" in compose


def test_compose_nginx_proxies_api_to_backend_service() -> None:
    nginx_config = read_project_file("docker/compose-nginx.conf")
    assert "listen 80;" in nginx_config
    assert "location /api/" in nginx_config
    assert "proxy_pass http://backend:8000;" in nginx_config
```

- [ ] **Step 2: 运行测试并确认失败**

运行：`uv run --with pytest pytest tests/test_docker_deployment.py -q`

预期：FAIL，提示 `Dockerfile` 不存在；部署文件尚未创建。

- [ ] **Step 3: 对新增测试执行静态检查**

运行：`uv run ruff check tests/test_docker_deployment.py && uv run ruff format tests/test_docker_deployment.py && git diff --check`

预期：PASS。

- [ ] **Step 4: 提交测试基线**

```bash
git add tests/test_docker_deployment.py
git commit -m "test: define Docker deployment contract"
```

### Task 2: 实现镜像、Nginx 与 Compose

**Files:**

- Create: `Dockerfile`
- Create: `docker/compose-nginx.conf`
- Create: `docker-compose.yml`
- Create: `docker-compose.env.example`

**Interfaces:**

- Consumes: Task 1 的文本契约、`pyproject.toml`、`uv.lock`、`web-ui/frontend/bun.lock`、`web-ui/backend.main:app`、`/api/health`。
- Produces: Docker targets `backend`/`frontend`；Compose 服务 `backend`/`frontend`；变量 `B2T_FRONTEND_PORT`、`B2T_WEB_UI_MODE`、`B2T_UID`、`B2T_GID` 与六项挂载路径变量。

- [ ] **Step 1: 创建多阶段 `Dockerfile`**

```dockerfile
FROM oven/bun:1 AS frontend-build
WORKDIR /src/web-ui/frontend
COPY web-ui/frontend/package.json web-ui/frontend/bun.lock ./
RUN bun install --frozen-lockfile
COPY web-ui/frontend/ ./
RUN bun run build

FROM python:3.12-slim AS backend
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
WORKDIR /app
RUN apt-get update && apt-get install --no-install-recommends -y ca-certificates curl ffmpeg pandoc && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.8.15 /uv /uvx /usr/local/bin/
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --extra web --extra cli
COPY b2t/ ./b2t/
COPY web-ui/backend/ ./web-ui/backend/
COPY summary_presets.toml context.toml ./
RUN .venv/bin/python -m playwright install --with-deps chromium \
    && useradd --create-home --uid 1000 b2t \
    && mkdir -p /app/transcriptions /app/db_data /app/chroma_data /ms-playwright \
    && chown -R b2t:b2t /app /ms-playwright
USER b2t
EXPOSE 8000
CMD [".venv/bin/uvicorn", "backend.main:app", "--app-dir", "web-ui", "--host", "0.0.0.0", "--port", "8000"]

FROM nginx:1.27-alpine AS frontend
COPY docker/compose-nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=frontend-build /src/web-ui/frontend/dist/ /usr/share/nginx/html/
EXPOSE 80
```

不得将 `config.toml` 写入 Dockerfile，也不得向 Uvicorn 添加 `--workers`。

- [ ] **Step 2: 创建 Compose 专用 Nginx 配置**

```nginx
server {
    listen 80;
    server_name _;
    root /usr/share/nginx/html;
    index index.html;
    client_max_body_size 200m;

    location /api/ {
        proxy_pass http://backend:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location / {
        try_files $uri /index.html;
    }
}
```

将其保存为 `docker/compose-nginx.conf`；不得改动 `docker/nginx.conf.template`，该文件仍服务于 `scripts/serve_frontend_nginx.sh` 的宿主机后端部署方式。

- [ ] **Step 3: 创建 `docker-compose.yml`**

```yaml
name: bilibili-to-text

services:
  backend:
    build: { context: ., target: backend }
    image: bilibili-to-text-backend:${B2T_IMAGE_TAG:-local}
    restart: unless-stopped
    user: "${B2T_UID:-1000}:${B2T_GID:-1000}"
    environment:
      B2T_WEB_UI_MODE: ${B2T_WEB_UI_MODE:-default}
    volumes:
      - ${B2T_CONFIG_PATH:-./config.toml}:/app/config.toml:ro
      - ${B2T_SUMMARY_PRESETS_PATH:-./summary_presets.toml}:/app/summary_presets.toml:ro
      - ${B2T_CONTEXT_PATH:-./context.toml}:/app/context.toml:ro
      - ${B2T_TRANSCRIPTIONS_DIR:-./transcriptions}:/app/transcriptions
      - ${B2T_DB_DIR:-./db_data}:/app/db_data
      - ${B2T_CHROMA_DIR:-./chroma_data}:/app/chroma_data
    healthcheck:
      test: ["CMD", "python", "-c", "from urllib.request import urlopen; assert urlopen('http://127.0.0.1:8000/api/health').status == 200"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 60s

  frontend:
    build: { context: ., target: frontend }
    image: bilibili-to-text-frontend:${B2T_IMAGE_TAG:-local}
    restart: unless-stopped
    depends_on:
      backend:
        condition: service_healthy
    ports:
      - "${B2T_FRONTEND_PORT:-6010}:80"
    healthcheck:
      test: ["CMD-SHELL", "wget -q -O- http://127.0.0.1/ >/dev/null 2>&1"]
      interval: 30s
      timeout: 5s
      retries: 3
```

不得发布 `backend` 端口；只使用 Compose 默认网络和 DNS 服务名 `backend`。

- [ ] **Step 4: 创建可提交环境模板**

```dotenv
B2T_IMAGE_TAG=local
B2T_FRONTEND_PORT=6010
B2T_WEB_UI_MODE=default
B2T_UID=1000
B2T_GID=1000
B2T_CONFIG_PATH=./config.toml
B2T_SUMMARY_PRESETS_PATH=./summary_presets.toml
B2T_CONTEXT_PATH=./context.toml
B2T_TRANSCRIPTIONS_DIR=./transcriptions
B2T_DB_DIR=./db_data
B2T_CHROMA_DIR=./chroma_data
```

将其保存为 `docker-compose.env.example`，不要使用 `.env.example`，因为 `.env.*` 已被忽略。

- [ ] **Step 5: 运行契约与 Compose 验证**

运行：`uv run --with pytest pytest tests/test_docker_deployment.py -q && docker compose --env-file docker-compose.env.example config`

预期：四个测试通过；Compose 仅有 `backend` 与 `frontend`，frontend 映射 `6010:80`，backend 没有 `ports` 且有六项挂载。

- [ ] **Step 6: 构建两个 target**

运行：`docker build --target backend -t bilibili-to-text-backend:verify . && docker build --target frontend -t bilibili-to-text-frontend:verify .`

预期：两次构建均退出 `0`；backend 包含 Uvicorn、`ffmpeg`、`pandoc` 和 Chromium，frontend 包含 Vite 构建产物。

- [ ] **Step 7: 提交部署实现**

```bash
git add Dockerfile docker/compose-nginx.conf docker-compose.yml docker-compose.env.example tests/test_docker_deployment.py
git commit -m "feat: add Docker Compose deployment"
```

### Task 3: 完成文档与构建上下文安全边界

**Files:**

- Modify: `.dockerignore`
- Modify: `README.md`
- Modify: `tests/test_docker_deployment.py`

**Interfaces:**

- Consumes: Task 2 的变量、服务名、健康接口与绑定挂载。
- Produces: 从克隆项目到浏览器访问的部署、更新、备份和故障排查说明。

- [ ] **Step 1: 为 README 新增失败的契约测试**

```python
def test_readme_documents_complete_docker_compose_workflow() -> None:
    readme = read_project_file("README.md")
    for fragment in (
        "docker-compose.env.example",
        "docker compose up -d --build",
        "docker compose logs -f backend",
        "docker compose down",
        "B2T_UID",
        "阿里云 OSS",
    ):
        assert fragment in readme
```

- [ ] **Step 2: 运行新测试并确认失败**

运行：`uv run --with pytest pytest tests/test_docker_deployment.py::test_readme_documents_complete_docker_compose_workflow -q`

预期：FAIL，README 尚未说明 `docker-compose.env.example` 工作流。

- [ ] **Step 3: 更新 `.dockerignore`**

缺失时追加以下排除项，并保留所有现有排除项：

```text
.env
.env.*
docker-compose.override.yml
```

继续忽略 `config.toml` 和三个数据目录。不要忽略 `Dockerfile`、`docker-compose.yml`、`docker-compose.env.example`、`summary_presets.toml` 或 `context.toml`。

- [ ] **Step 4: 在 README 增加“完整 Docker Compose 部署”章节**

将该章节放在“启动 Web UI”之后、“宿主机后端 + Nginx 容器部署”之前，且必须包含以下命令：

```bash
cp docker-compose.env.example .env
docker compose up -d --build
docker compose ps
docker compose logs -f backend
docker compose down
```

说明浏览器访问地址为 `http://127.0.0.1:${B2T_FRONTEND_PORT:-6010}`、Nginx 是唯一公开服务、六个挂载路径在 `docker compose down` 后仍保留；说明 `.env` 可设置 `B2T_WEB_UI_MODE=open-public`，Linux 用户可设置 `B2T_UID=$(id -u)` 与 `B2T_GID=$(id -g)`，且带阿里云 OSS 凭证的现有 `config.toml` 不得提交。补充更新（`docker compose up -d --build`）、备份（复制全部挂载前暂停写入）和健康检查失败排查（`docker compose logs backend`）。将 README 的“Docker/Cli 未经测试”改为 Docker Compose 受项目支持、但供应商凭证和外部网络可用性由部署者负责的表述。

- [ ] **Step 5: 运行全量静态验证**

运行：`uv run --with pytest pytest tests/test_docker_deployment.py -q && uv run ruff check tests/test_docker_deployment.py && uv run ruff format tests/test_docker_deployment.py && git diff --check && docker compose --env-file docker-compose.env.example config`

预期：pytest、Ruff 与 Compose 渲染均通过。

- [ ] **Step 6: 提交文档**

```bash
git add .dockerignore README.md tests/test_docker_deployment.py
git commit -m "docs: document Docker Compose deployment"
```

### Task 4: 执行容器端到端与持久化验证

**Files:**

- Modify: `README.md`（仅当实际命令暴露说明不准确时）

**Interfaces:**

- Consumes: Task 2 的 Compose 文件、一个不提交的临时环境文件与本机 Docker 守护进程。
- Produces: 健康检查、Nginx 代理和容器重建后数据仍存在的验证证据。

- [ ] **Step 1: 准备隔离的非敏感验证目录与环境文件**

在仓库根目录运行下列 PowerShell。它会复制配置文件但不显示内容，并为验证保留端口 `16010`：

```powershell
$verifyRoot = Join-Path $env:TEMP "b2t-docker-verify-$([guid]::NewGuid().ToString('N'))"
$verifyEnv = Join-Path $verifyRoot '.env'
New-Item -ItemType Directory -Force -Path $verifyRoot, "$verifyRoot/transcriptions", "$verifyRoot/db_data", "$verifyRoot/chroma_data" | Out-Null
Copy-Item config.toml, summary_presets.toml, context.toml -Destination $verifyRoot
@"
B2T_FRONTEND_PORT=16010
B2T_CONFIG_PATH=$verifyRoot/config.toml
B2T_SUMMARY_PRESETS_PATH=$verifyRoot/summary_presets.toml
B2T_CONTEXT_PATH=$verifyRoot/context.toml
B2T_TRANSCRIPTIONS_DIR=$verifyRoot/transcriptions
B2T_DB_DIR=$verifyRoot/db_data
B2T_CHROMA_DIR=$verifyRoot/chroma_data
"@ | Set-Content -Encoding utf8 -NoNewline $verifyEnv
```

不得输出 `config.toml` 内容，因为其中包含凭证。

- [ ] **Step 2: 构建并启动应用**

运行：`docker compose --project-name b2t-docker-verify --env-file "$verifyEnv" up -d --build; docker compose --project-name b2t-docker-verify --env-file "$verifyEnv" ps`

预期：`backend` 与 `frontend` 均显示 `healthy`。

- [ ] **Step 3: 验证同源代理和持久化**

运行：`(Invoke-RestMethod http://127.0.0.1:16010/api/health).status`

预期：`ok`。

运行下列命令验证持久化：

```powershell
New-Item -ItemType File -Path "$verifyRoot/db_data/.docker-persistence-sentinel" | Out-Null
docker compose --project-name b2t-docker-verify --env-file "$verifyEnv" down
docker compose --project-name b2t-docker-verify --env-file "$verifyEnv" up -d
Test-Path "$verifyRoot/db_data/.docker-persistence-sentinel"
```

预期：sentinel 文件仍存在，证明 Compose 未删除绑定挂载。

- [ ] **Step 4: 清理容器但保留测试数据**

运行：`docker compose --project-name b2t-docker-verify --env-file "$verifyEnv" down --remove-orphans`

预期：容器和网络已移除，临时宿主机数据目录仍存在供检查。

- [ ] **Step 5: 仅在需要时提交验证导致的 README 修正**

```bash
git add README.md
git commit -m "docs: clarify verified Docker deployment steps"
```

仅当 Task 4 修正了 README 文本时创建该提交；否则在交接中记录命令输出，不创建空提交。
