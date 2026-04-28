# bilibili-to-text

Bilibili 视频转文字工具，支持下载音频、语音转录、生成 Markdown/TXT、LLM 总结，以及通过 Web UI 管理处理结果。

当前 README 只覆盖 CLI 和前后端 Web UI 的本地运行。`monitor` 相关能力仍保留在代码中，但暂不作为开源上手流程的一部分展开。

## 功能

- 使用 `yutto` 下载 Bilibili 视频音频
- 语音转文字：
  - Groq Whisper-compatible ASR
  - Alibaba DashScope / Qwen ASR
- 转录 JSON 转 Markdown/TXT
- 使用 LiteLLM-compatible 接口生成总结
- 本地、MinIO、Alibaba Cloud OSS 三种产物存储后端
- FastAPI + Vue/Vite Web UI
- 可选 RAG 检索历史转录内容
- Markdown 派生的 PDF/PNG/HTML 转换工具

## 开源前隐私检查

不要提交下面这些本地文件或目录：

- `config.toml`、`.env*`、`*.local.toml`：通常包含 API Key、Bilibili Cookie、对象存储密钥
- `transcriptions/`、`web-ui/transcriptions/`：音频、转录文本、总结内容
- `db_data/`、`chroma_data/`：历史数据库、向量数据库、monitor 状态
- `web-ui/logs/`：本地服务日志
- `.claude/`：本机 Claude/Codex 工具权限配置
- `test-audio/`、`doubao-test/`、`AIFeedTracker/`：本地测试或外部实验数据

仓库已用 `.gitignore` 和 `.dockerignore` 忽略上述内容。开源前仍建议再跑一次：

```bash
git status --short
git grep -n -E "(api[_-]?key|secret|token|password|cookie|authorization|bearer|sk-)"
```

如果之前曾把真实密钥提交进 git 历史，应先吊销并重新生成密钥；仅从当前版本删除文件并不能清理历史记录。

## 目录结构

```text
.
|-- b2t/                  # 核心 Python 包和 CLI pipeline
|-- web-ui/backend/       # FastAPI 后端
|-- web-ui/frontend/      # Vue + Vite 前端
|-- tests/                # Pytest 测试
|-- scripts/              # 辅助脚本
|-- config.toml.example   # 本地配置模板
|-- summary_presets.toml  # 总结 prompt presets
|-- justfile              # 常用本地命令
`-- Dockerfile            # 单容器 Web UI 部署
```

## 环境要求

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- [Bun](https://bun.sh/)
- `ffmpeg`
- `pandoc`
- 需要 PDF/PNG 渲染时安装 Playwright Chromium

macOS 可用 Homebrew 安装系统依赖：

```bash
brew install ffmpeg pandoc
```

## 从克隆到运行

1. 克隆仓库并安装 Python 依赖：

```bash
git clone https://github.com/<owner>/bilibili-to-text.git
cd bilibili-to-text
uv sync
```

2. 安装前端依赖：

```bash
cd web-ui/frontend
bun install
cd ../..
```

3. 复制并编辑本地配置：

```bash
cp config.toml.example config.toml
```

最低配置建议先走 `Groq + local storage`，不需要 MinIO/OSS：

```toml
[storage]
backend = "local"

[stt]
profile = "groq-main"

[stt.profiles.groq-main]
groq_api_key = "your-groq-api-key"
storage_profile = "local"

[summarize]
profile = "groq-main"

[summarize.profiles.groq-main]
api_key = "your-groq-api-key"
```

如果使用 DashScope/Qwen ASR，需要把 `[stt].profile` 改为 `qwen-main`，并配置 `storage.minio` 或 `storage.alicloud`，因为 Qwen 文件转录需要可公网访问的临时音频 URL。

4. 可选：安装浏览器渲染依赖：

```bash
uv run playwright install chromium
```

5. 启动前后端：

```bash
just web on
```

访问：

```text
http://127.0.0.1:6010
```

后端默认监听 `8000`，前端默认监听 `6010`。停止服务：

```bash
just web off
```

## 手动启动前后端

后端：

```bash
uv run uvicorn backend.main:app --app-dir web-ui --host 0.0.0.0 --port 8000 --reload
```

前端：

```bash
cd web-ui/frontend
bun run dev
```

如果后端端口不是 `8000`：

```bash
cd web-ui/frontend
bun run dev --backend-port 8001
```

或：

```bash
B2T_BACKEND_PORT=8001 bun run dev
```

## CLI 使用

处理一个 Bilibili 视频：

```bash
uv run b2t "https://www.bilibili.com/video/BVxxxxxxxxxx"
```

指定配置、输出目录和总结 preset：

```bash
uv run b2t "https://www.bilibili.com/video/BVxxxxxxxxxx" \
  --config config.toml \
  --output ./transcriptions \
  --summary-preset timeline_merge \
  --summary-profile groq-main
```

跳过 LLM 总结：

```bash
uv run b2t "https://www.bilibili.com/video/BVxxxxxxxxxx" --no-summary
```

进入交互式 CLI：

```bash
uv run b2t
```

## open-public Web UI 模式

公开试用时可以启动 `open-public` 模式：

```bash
just web-open-public on
```

该模式会禁用上传音频、删除历史、本地项目 API Key，并要求用户在页面中输入自己的 DashScope API Key。

注意：`open-public` 模式仍依赖 Qwen ASR 的音频临时 URL 流程，因此本地 `config.toml` 里仍需要配置可用的 MinIO 或 Alibaba Cloud OSS。

## Docker

构建镜像：

```bash
docker build -t bilibili-to-text:latest .
```

运行：

```bash
docker run --rm \
  -p 6010:6010 \
  -v "$(pwd)/config.toml:/app/config.toml:ro" \
  -v "$(pwd)/transcriptions:/app/transcriptions" \
  bilibili-to-text:latest
```

访问：

```text
http://127.0.0.1:6010
```

容器内会启动 FastAPI 后端和 Nginx 前端，外部只需要访问 `6010`。

## 测试

```bash
uv run pytest
```

## 生成数据

常见运行产物：

- `transcriptions/`：音频、转录、总结和派生文件
- `web-ui/transcriptions/`：Web UI 侧转录产物
- `db_data/`：历史数据库和状态文件
- `chroma_data/`：RAG 向量数据库
- `web-ui/logs/`：本地前后端日志

这些文件可能包含隐私内容或凭据衍生信息，默认不应提交。

## License

当前仓库还没有 license 文件。正式开源前请先选择并添加许可证。
