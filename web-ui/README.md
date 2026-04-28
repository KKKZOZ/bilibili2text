## bilibili-to-text Web UI

Web UI 由 FastAPI 后端和 Vue/Vite 前端组成。完整的从 clone 到运行流程见根目录 [README.md](../README.md)。

### 目录结构

- `backend/`：FastAPI 接口与任务队列
- `frontend/`：Vue + Vite 前端，使用 Bun 管理依赖

### 配置

Web UI 使用项目根目录的：

- `config.toml`
- `summary_presets.toml`

先在根目录复制配置模板：

```bash
cp config.toml.example config.toml
```

默认建议先使用 `Groq + local storage` 跑通本地流程。DashScope/Qwen ASR 需要 MinIO 或 Alibaba Cloud OSS 提供公网临时音频 URL。

### 一键启动

在项目根目录执行：

```bash
just web on
```

默认访问：

```text
http://127.0.0.1:6010
```

停止：

```bash
just web off
```

### 手动启动

后端：

```bash
uv run uvicorn backend.main:app --app-dir web-ui --host 0.0.0.0 --port 8000 --reload
```

前端：

```bash
cd web-ui/frontend
bun install
bun run dev
```

如果后端端口不是 `8000`：

```bash
bun run dev --backend-port 8001
```

### open-public 模式

```bash
just web-open-public on
```

该模式会禁用上传音频、删除历史、本地项目 API Key，并要求用户在页面里输入自己的 DashScope API Key。由于该模式使用 Qwen ASR，本地 `config.toml` 仍需要配置可用的 MinIO 或 Alibaba Cloud OSS。

### Docker

在项目根目录执行：

```bash
docker build -t bilibili-to-text:latest .
docker run --rm \
  -p 6010:6010 \
  -v "$(pwd)/config.toml:/app/config.toml:ro" \
  -v "$(pwd)/transcriptions:/app/transcriptions" \
  bilibili-to-text:latest
```
