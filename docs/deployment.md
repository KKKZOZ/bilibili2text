# 部署与配置

前后端分离部署到 Cloudflare：参见 [Pages + Tunnel 部署指南](cloudflare-deployment.md)。

## 环境要求

| 依赖 | 用途 | 安装方式 |
|------|------|----------|
| Python 3.12+ | 运行核心包 | [uv](https://docs.astral.sh/uv/) |
| uv | Python 包管理 | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Bun | 前端构建与开发 | `npm install -g bun` |
| ffmpeg | 音频处理（格式转换/分块） | `brew install ffmpeg` |
| pandoc | Markdown ↔ HTML/PDF/TXT | `brew install pandoc` |
| Playwright Chromium | PDF/PNG 渲染 | `playwright install chromium` |

macOS 一键安装系统依赖：

```bash
brew install ffmpeg pandoc
playwright install chromium
```

## 快速启动

### 1. 安装依赖

```bash
git clone https://github.com/KKKZOZ/bilibili2text.git
cd bilibili2text
uv sync --extra web
cd web-ui/frontend && bun install && cd ../..
```

### 2. 配置 config.toml

```bash
cp config.toml.example config.toml
```

**最简配置**（阿里云 OSS + Qwen ASR + DeepSeek LLM）：

```toml
[storage]
backend = "alicloud"

[storage.alicloud]
region = "cn-shanghai"
bucket = "your-oss-bucket"
access_key_id = "LTAI5txxxxxxxxxx"
access_key_secret = "xxxxxxxxxxxxxxxxxxxxxxxx"
base_prefix = "b2t"
temporary_prefix = "temp-audio"

[stt]
profile = "qwen-main"

[stt.profiles.qwen-main]
provider = "qwen"
language = "zh"
storage_profile = "alicloud"
qwen_api_key = "sk-xxxxxxxxxxxxxxxx"
qwen_model = "qwen3-asr-flash-filetrans"

[summarize]
profile = "deepseek-main"

[summarize.profiles.deepseek-main]
provider = "deepseek"
model = "deepseek-v4-pro"
api_base = "https://api.deepseek.com"
api_key = "sk-xxxxxxxxxxxxxxxx"
```

### 3. 启动

终端 1 — 后端（默认 open-public，监听地址、端口、CORS 在 `config.toml` 的 `[backend]` 中配置）：

```bash
uv run b2t backend
```

终端 2 — 前端：

```bash
cd web-ui/frontend && bun run dev
```

浏览器访问 `http://localhost:6010`

## 配置项完整参考

### `[download]` — 下载与输出

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `audio_quality` | str | `"30216"` | yutto 音频质量码 |
| `output_dir` | str | `"./transcriptions"` | 转录产物的本地输出目录 |
| `db_dir` | str | `"./db_data"` | SQLite 历史数据库目录 |

### `[storage]` — 产物存储

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `backend` | str | `"local"` | 存储后端：`local` / `minio` / `alicloud` |

**MinIO 子配置 `[storage.minio]`**：

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `endpoint` | str | `"127.0.0.1:9000"` | MinIO 服务地址 |
| `bucket` | str | `""` | Bucket 名称 |
| `access_key` | str | `""` | Access Key |
| `secret_key` | str | `""` | Secret Key |
| `secure` | bool | `false` | 是否使用 HTTPS |
| `region` | str | `""` | 区域 |
| `base_prefix` | str | `"b2t"` | 对象 Key 前缀 |
| `temporary_url_expire_seconds` | int | `7200` | 预签名 URL 过期时间 |

**阿里云 OSS 子配置 `[storage.alicloud]`**：

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `region` | str | `""` | OSS 地域 |
| `bucket` | str | `""` | Bucket 名称 |
| `access_key_id` | str | `""` | RAM AccessKey ID |
| `access_key_secret` | str | `""` | RAM AccessKey Secret |
| `base_prefix` | str | `"b2t"` | 对象 Key 前缀 |
| `temporary_prefix` | str | `"temp-audio"` | 临时音频前缀 |
| `temporary_url_expire_seconds` | int | `7200` | 临时音频预签名 URL 过期时间 |
| `auto_create_bucket` | bool | `false` | 是否自动创建 Bucket |
| `public_base_url` | str | `""` | 自定义 CDN 域名 |

### `[stt]` — 语音转文字

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `profile` | str | `"qwen"` | 默认使用的 STT profile |

**Qwen profile `[stt.profiles.<name>]`**：

| 字段 | 说明 |
|------|------|
| `provider` | `"qwen"` |
| `language` | 语言代码，默认 `"zh"` |
| `storage_profile` | 关联的存储后端，需支持公网 URL |
| `qwen_api_key` | DashScope API Key |
| `qwen_model` | `qwen3-asr-flash-filetrans` 或 `fun-asr` |
| `qwen_base_url` | API 地址 |

**Groq profile**：

| 字段 | 说明 |
|------|------|
| `provider` | `"groq"` |
| `groq_api_key` | Groq API Key |
| `groq_model` | `whisper-large-v3-turbo` |
| `groq_chunk_length` | 分块时长（秒），默认 1800 |
| `groq_overlap` | 重叠秒数，默认 10 |

### `[summarize]` — LLM 总结

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `profile` | str | — | 默认模型 profile |
| `enable_thinking` | bool | `false` | 是否启用推理模式（思维链） |
| `preset` | str | `"timeline_merge"` | 默认总结 preset |
| `presets_file` | str | `"summary_presets.toml"` | preset 模板文件 |
| `context_file` | str | `"context.toml"` | 作者上下文文件 |

**模型 profile `[summarize.profiles.<name>]`**：

| 字段 | 说明 |
|------|------|
| `provider` | `bailian` / `deepseek` / `groq` / `openrouter` / `openai_compatible` |
| `model` | 模型名称 |
| `api_base` | API 地址（可选，有默认值） |
| `api_key` | API Key |
| `providers` | 仅 openrouter：provider 优先顺序列表 |

### `[fancy_html]` — 美化 HTML

| 字段 | 说明 |
|------|------|
| `profile` | 使用的 LLM profile（引用 `[summarize.profiles.<name>]`） |

### `[converter]` — 格式转换

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `min_length` | int | `60` | JSON → Markdown 合并短句的最小长度 |

### `[rag]` — 知识检索

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `enabled` | bool | `false` | 是否启用 RAG |
| `collection_name` | str | `"b2t_rag"` | ChromaDB 集合名 |
| `chroma_dir` | str | `"./chroma_data"` | ChromaDB 数据目录 |
| `chunk_size` | int | `800` | 分块大小 |
| `chunk_overlap` | int | `100` | 重叠字符数 |
| `top_k` | int | `5` | 检索返回数量 |
| `embedding` | object | — | 嵌套配置：provider/model/api_key |
| `llm_profile` | str | — | 回答生成的 LLM profile |

### `[monitor]` — UP 主监控

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `enabled` | bool | `false` | 是否启用 |
| `state_file` | str | `"./db_data/bilibili_monitor_state.json"` | 监控状态持久化 |
| `default_check_interval` | int | `300` | 默认检查间隔（秒） |

运行 `uv run b2t monitor` 打开 Textual 面板，自动展示最近 5 个视频、历史总结状态、
检查次数和下一次检查倒计时。↑↓ 选择视频，←→ 切换 UP 主，Enter 选择生成总结、
阅读报告或两者都生成，Esc 取消。Ctrl+C 退出监控，已提交的后台任务继续运行。

生成操作需要另行运行 `uv run b2t backend`。monitor 使用 `[backend].host/port` 连接 API，
模型、profile、模板均由 backend 默认配置决定。结果由 backend 保存，TUI 查询并展示任务进度。
监控不会自动处理未总结视频，旧版监控处理配置会被忽略。
`--once` 或将输出重定向到文件时使用普通日志输出，不支持手动提交任务。

**监控的 UP 主 `[[monitor.creators]]`**：

| 字段 | 说明 |
|------|------|
| `uid` | B站用户 UID |
| `name` | 显示名称 |
| `check_interval` | 检查间隔（秒） |

## 环境变量

| 变量 | 说明 |
|------|------|
| `B2T_CONFIG` | 覆盖配置文件路径 |
| `B2T_WEB_UI_MODE` | `open-public`（默认）或 `default` |
| `B2T_BACKEND_PORT` | 前端代理的后端端口（默认 `8000`） |
| `B2T_FRONTEND_PORT` | Nginx 容器的前端端口（默认 `6010`） |
| `B2T_CORS_ORIGINS` | 后端允许的前端 Origin，逗号分隔；设置后覆盖 `[backend].cors_origins` |
| `VITE_API_BASE_URL` | 前端构建时的后端 Origin（如 `https://api.example.com`），不带 `/api`；默认同源 |

## LLM Provider 对照表

| provider 值 | 服务商 | 默认 api_base |
|------------|--------|---------------|
| `bailian` | 阿里云百炼 | `https://dashscope.aliyuncs.com/compatible-mode/v1` |
| `deepseek` | DeepSeek | `https://api.deepseek.com` |
| `groq` | Groq | `https://api.groq.com/openai/v1` |
| `openrouter` | OpenRouter | `https://openrouter.ai/api/v1` |
| `openai_compatible` | 自定义 | `https://api.openai.com/v1`（可覆盖） |
