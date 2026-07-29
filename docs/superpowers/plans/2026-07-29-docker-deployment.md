# Docker 部署实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为项目提供包含 FastAPI、Vue/Nginx、Playwright Chromium、ffmpeg 和 pandoc 的一键 Docker Compose 部署，并持久化本地状态。

**Architecture:** 使用一个多阶段 `Dockerfile` 构建后端运行镜像和前端静态资源镜像；`docker-compose.yml` 启动 `backend` 与 `frontend`，由 Nginx 将 `/api/` 代理到 `backend:8000`。宿主机以只读文件挂载配置，以读写目录挂载转录、SQLite 和 Chroma 状态；不启动 MinIO，继续使用阿里云 OSS。

**Tech Stack:** Docker multi-stage builds, Docker Compose, Python 3.12, `uv`, Bun/Vite, Nginx, Uvicorn, Playwright Chromium, ffmpeg, pandoc。

## Global Constraints

- 不在 Compose 中增加 MinIO、数据库服务、HTTPS 证书或镜像仓库发布配置。
- 必须预装 `ffmpeg`、`pandoc` 和 Playwright Chromium。
- 必须只读挂载 `config.toml`、`summary_presets.toml`、`context.toml`，并读写挂载 `transcriptions`、`db_data`、`chroma_data`。
- 后端固定监听容器内 `8000`，前端只对宿主机暴露可配置端口，默认 `6010`。
- 后端使用单 worker、非 root 用户运行，并通过 `B2T_WEB_UI_MODE` 支持 `default` 与 `open-public`。
- 保留现有 `b2t/download/yutto_cli.py` 未提交修改，不将其纳入任何提交。
- 前端改动后运行 `bun run format`；本次无 Python 后端代码改动，不运行 `ruff`。

---

### Task 1: 准备 Docker 构建上下文与忽略规则

**Files:**
- Create: `Dockerfile`
- Modify: `.dockerignore`

**Interfaces:**
- Produces: `backend` 和 `frontend` 两个 Compose 服务可使用的镜像构建目标，目标名分别为 `backend` 和 `frontend`。

- [ ] **Step 1: 编写 Dockerfile 的前端构建阶段**

  使用锁文件安装依赖并构建静态资源：

  ```dockerfile
  FROM oven/bun:1 AS frontend-build
  WORKDIR /src/web-ui/frontend
  COPY web-ui/frontend/package.json web-ui/frontend/bun.lock ./
  RUN bun install --frozen-lockfile
  COPY web-ui/frontend/ ./
  RUN bun run build
  ```

- [ ] **Step 2: 编写后端运行阶段**

  基于 Python 3.12 slim 安装系统库和 `uv`，复制项目代码，执行 `uv sync --frozen --no-dev --extra web`；安装 Chromium 及依赖，创建非 root 用户并设置 `/app` 为工作目录。运行入口固定为：

  ```dockerfile
  CMD ["uv", "run", "--no-sync", "uvicorn", "backend.main:app", "--app-dir", "web-ui", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
  ```

- [ ] **Step 3: 增加 frontend 运行阶段**

  从官方 Nginx Alpine 镜像复制 `frontend-build` 的 `dist` 和容器专用模板 `docker/nginx.compose.conf.template`，保留 `/etc/nginx/templates/default.conf.template` 的环境变量渲染机制。

- [ ] **Step 4: 排除不应进入构建上下文的目录**

  在 `.dockerignore` 中追加 `.git`、`.venv`、`node_modules`、`dist`、`chroma_data`、`db_data`、`transcriptions`、日志、缓存和本地密钥文件，确保数据不会进入镜像层。

- [ ] **Step 5: 进行静态构建文件检查**

  运行：

  ```powershell
  docker build --target backend -t bilibili-to-text:plan-check .
  docker build --target frontend -t bilibili-to-text-web:plan-check .
  ```

  预期：两个 target 均成功完成，且构建日志没有将数据目录或 `config.toml` 复制进镜像的步骤。

- [ ] **Step 6: 提交构建基础设施**

  ```powershell
  git add Dockerfile .dockerignore docker/nginx.compose.conf.template
  git commit -m "build: add Docker images for web deployment"
  ```

### Task 2: 编排服务与持久化挂载

**Files:**
- Create: `docker-compose.yml`
- Create: `.env.example`

**Interfaces:**
- Consumes: Task 1 的 `backend`、`frontend` 构建目标。
- Produces: `docker compose up -d --build` 可启动的 `backend` 和 `frontend` 服务；前端公开 `/api/health`。

- [ ] **Step 1: 定义 Compose 变量和目录挂载**

  使用以下默认值与容器路径：

  ```yaml
  services:
    backend:
      build:
        context: .
        target: backend
      environment:
        B2T_WEB_UI_MODE: ${B2T_WEB_UI_MODE:-default}
      volumes:
        - ${B2T_CONFIG_PATH:-./config.toml}:/app/config.toml:ro
        - ${B2T_SUMMARY_PRESETS_PATH:-./summary_presets.toml}:/app/summary_presets.toml:ro
        - ${B2T_CONTEXT_PATH:-./context.toml}:/app/context.toml:ro
        - ${B2T_TRANSCRIPTIONS_DIR:-./transcriptions}:/app/transcriptions
        - ${B2T_DB_DIR:-./db_data}:/app/db_data
        - ${B2T_CHROMA_DIR:-./chroma_data}:/app/chroma_data
  ```

- [ ] **Step 2: 增加 backend 健康检查与重启策略**

  健康检查使用项目已有端点：

  ```yaml
  healthcheck:
    test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3)"]
    interval: 30s
    timeout: 5s
    retries: 5
    start_period: 30s
  restart: unless-stopped
  ```

- [ ] **Step 3: 定义 frontend 服务和内部代理**

  前端使用 `B2T_FRONTEND_PORT` 默认 `6010`，只绑定宿主机该端口；Nginx 通过 Compose 网络访问 `backend:8000`。设置 `depends_on.backend.condition: service_healthy` 和前端健康检查。

- [ ] **Step 4: 编写 `.env.example`**

  提供端口、模式、镜像标签和六个宿主机路径变量示例，并注释 `config.toml` 含 API 密钥，不应提交真实 `.env`。

- [ ] **Step 5: 验证 Compose 静态配置**

  运行：

  ```powershell
  docker compose --env-file .env.example config
  ```

  预期：输出包含 `backend`、`frontend`、`backend:8000`、端口 `6010`、六项挂载和健康检查，且无变量未解析警告。

- [ ] **Step 6: 提交 Compose 编排**

  ```powershell
  git add docker-compose.yml .env.example
  git commit -m "feat: add Docker Compose deployment"
  ```

### Task 3: 更新部署文档与运维流程

**Files:**
- Modify: `README.md`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: Task 2 的 Compose 变量和服务名。
- Produces: 用户可按文档完成首次部署、更新、日志查看、停止和数据备份。

- [ ] **Step 1: 增加 Docker 快速开始章节**

  写明复制 `config.toml.example`、按需准备 `summary_presets.toml`/`context.toml`、执行 `docker compose up -d --build`、访问 `${B2T_FRONTEND_PORT:-6010}`，并说明继续使用阿里云 OSS、无需 MinIO。

- [ ] **Step 2: 增加日常运维命令**

  文档必须包含：

  ```powershell
  docker compose ps
  docker compose logs -f backend
  docker compose logs -f frontend
  docker compose up -d --build
  docker compose down
  ```

  同时说明 `down` 不删除宿主机绑定目录，以及备份 `transcriptions`、`db_data`、`chroma_data` 和三个配置文件的建议。

- [ ] **Step 3: 更新平台支持说明**

  将当前 README 中“Docker 未经测试”的表述改为描述实际支持边界：需要 Docker Compose、可联网拉取基础镜像和阿里云 OSS；HTTPS、MinIO 和外部数据库不由本方案提供。

- [ ] **Step 4: 确认忽略本地部署文件**

  在 `.gitignore` 中加入 `.env`（保留 `.env.example`），避免包含密钥的运行配置被提交。

- [ ] **Step 5: 执行文档格式检查**

  运行：

  ```powershell
  git diff --check
  ```

  预期：无空白错误；README 的命令、变量名与 `docker-compose.yml` 完全一致。

- [ ] **Step 6: 提交文档与忽略规则**

  ```powershell
  git add README.md .gitignore
  git commit -m "docs: document Docker deployment"
  ```

### Task 4: 完成端到端验证

**Files:**
- Modify: none
- Test artifacts: Docker images and Compose containers only; do not commit generated data.

**Interfaces:**
- Consumes: Tasks 1–3 的全部 Docker 资产。
- Produces: 可复现的构建、启动、健康检查、代理和持久化验证结果。

- [ ] **Step 1: 运行最终 Compose 配置检查**

  ```powershell
  docker compose --env-file .env.example config --quiet
  ```

  预期：退出码为 `0`。

- [ ] **Step 2: 构建并启动服务**

  ```powershell
  docker compose up -d --build
  docker compose ps
  ```

  预期：两个服务为 `running`，backend 与 frontend 的健康状态最终为 `healthy`。

- [ ] **Step 3: 验证 API 与 Nginx 代理**

  ```powershell
  Invoke-WebRequest http://127.0.0.1:6010/api/health
  ```

  预期：HTTP `200`，响应体包含 `"status":"ok"`。

- [ ] **Step 4: 验证持久化路径**

  在宿主机数据目录写入一个不会影响应用的标记文件，执行 `docker compose down` 后再次 `up -d`，确认标记文件仍存在；不删除任何目录。

- [ ] **Step 5: 收集失败诊断信息**

  若任一检查失败，运行 `docker compose logs --tail=200 backend frontend`，根据具体错误修正 Dockerfile、权限或代理配置后重复本任务；未通过前不声称部署完成。

- [ ] **Step 6: 最终检查工作树**

  ```powershell
  git diff --check
  git status --short
  ```

  预期：只显示本任务提交后的用户变更（包括原有的 `b2t/download/yutto_cli.py` 未提交修改），不包含生成的数据目录或密钥文件。

