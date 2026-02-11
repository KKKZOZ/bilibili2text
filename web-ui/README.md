## bilibili-to-text Web UI

### 目录结构

- `backend/main.py`：FastAPI 接口
- `frontend/`：Vue + Vite 前端（使用 Bun）

### 1. 准备配置

项目根目录需要以下配置文件：

- `config.toml`（参考 `config.toml.example`）
- `summary_presets.toml`（参考 `summary_presets.toml.example`）

`[stt]` 可通过 `provider` 选择转录引擎：

- `provider = "qwen"`：DashScope + OSS 上传流程
- `provider = "groq"`：Groq 本地分块转录流程

`[polish]` 可指定总结 preset：

- `preset`：默认使用的总结 preset 名称
- `presets_file`：总结 preset TOML 文件路径（默认 `summary_presets.toml`）

### 2. 启动后端（FastAPI）

先在项目根目录执行一次依赖安装：

```bash
uv sync
```

然后在 `web-ui` 目录下执行：

```bash
uv run uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```

后端接口：

- `POST /api/process`：提交 bilibili URL，返回 `job_id`
- `GET /api/process/{job_id}`：查询任务阶段与进度
- `GET /api/summary-presets`：获取可用总结 presets
- `GET /api/download/{download_id}`：下载生成的 Markdown

### 3. 启动前端（Vue + Bun）

在 `web-ui/frontend` 目录下执行：

```bash
bun install
bun run dev
```

默认访问：`http://127.0.0.1:6010`

### 4. 使用流程

1. 在前端输入 bilibili 视频 URL，按需选择是否启用总结与总结 preset，然后提交。
2. 前端自动轮询并展示当前阶段（下载 / 转录 / 总结等）。
3. 点击下载按钮获取原文或总结 Markdown。

### 5. Docker 打包与运行（前后端同容器）

在项目根目录执行构建：

```bash
docker build -t bilibili-to-text:latest .
```

运行容器（只暴露前端端口）：

```bash
docker run --rm \
  -p 6010:6010 \
  -v $(pwd)/config.toml:/app/config.toml:ro \
  -v $(pwd)/transcriptions:/app/transcriptions \
  bilibili-to-text:latest
```

访问地址：`http://127.0.0.1:6010`

说明：

容器内会同时启动：

- FastAPI 后端（默认 `127.0.0.1:8000`，仅容器内可访问）
- Nginx 前端静态服务（默认 `0.0.0.0:6010`，对外暴露）
- 前端通过 Nginx 转发 `/api` 到后端，所以无需暴露后端端口。

可选环境变量：

- `FRONTEND_PORT`：前端服务端口（默认 `6010`）
- `BACKEND_HOST`：后端监听地址（默认 `127.0.0.1`）
- `BACKEND_PORT`：后端监听端口（默认 `8000`）
- `B2T_CONFIG`：配置文件路径（默认 `/app/config.toml`）

示例（改前端端口到 `8080`）：

```bash
docker run --rm \
  -e FRONTEND_PORT=8080 \
  -p 8080:8080 \
  -v $(pwd)/config.toml:/app/config.toml:ro \
  -v $(pwd)/transcriptions:/app/transcriptions \
  bilibili-to-text:latest
```
