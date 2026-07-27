# 架构总览

## 系统分层

```mermaid
graph TB
    subgraph 用户入口
        CLI[CLI 命令行<br/>b2t &lt;url&gt;]
        WEB[Web UI<br/>Vue 3 + Vite]
    end

    subgraph 接入层
        API[FastAPI 后端<br/>REST API + SSE]
        JOB[任务队列<br/>线程池 + 状态机]
    end

    subgraph 核心Pipeline
        PIPE[run_pipeline<br/>编排引擎]
        DL[download<br/>yutto 音频下载]
        STT[stt<br/>语音转文字]
        CNV[converter<br/>格式转换]
        SUM[summarize<br/>LLM 总结]
    end

    subgraph 基础设施
        STORE[storage<br/>本地/MinIO/OSS]
        RAG[rag<br/>ChromaDB 向量检索]
        HIST[history<br/>SQLite 元数据]
        MON[monitor<br/>UP 主监控]
    end

    subgraph 外部服务
        BILI[(Bilibili API<br/>视频元数据)]
        ASR_OSS[(阿里云 OSS<br/>音频中转)]
        ASR_API[(DashScope ASR<br/>qwen3-asr-flash)]
        LLM_API[(DeepSeek API<br/>deepseek-v4-pro)]
        FS[(飞书 Bot<br/>通知推送)]
    end

    CLI --> PIPE
    WEB --> API --> JOB --> PIPE
    PIPE --> DL --> BILI
    PIPE --> STT --> ASR_OSS
    STT --> ASR_API
    PIPE --> CNV
    PIPE --> SUM --> LLM_API
    PIPE --> STORE --> ASR_OSS
    PIPE --> HIST
    API --> RAG
    MON --> PIPE --> FS
```

## 模块依赖关系

```mermaid
graph LR
    config.py[config.py<br/>配置加载中心] --> download
    config.py --> stt
    config.py --> storage
    config.py --> summarize
    config.py --> converter
    config.py --> rag
    config.py --> monitor

    pipeline.py[pipeline.py<br/>核心编排] --> download
    pipeline.py --> stt
    pipeline.py --> converter
    pipeline.py --> summarize
    pipeline.py --> storage

    cli.py --> pipeline.py
    cli.py --> history.py
    cli.py --> monitor

    web-ui/backend --> pipeline.py
    web-ui/backend --> history.py
    web-ui/backend --> storage
    web-ui/backend --> rag
```

## 核心模块职责

| 模块 | 路径 | 一句话职责 |
|------|------|-----------|
| **配置中心** | `b2t/config.py` | TOML 加载、验证、dataclass 建模（31 个配置类） |
| **下载** | `b2t/download/` | 通过 yutto 下载 B站视频音频流，提取元数据和 BV 号 |
| **语音转写** | `b2t/stt/` | 多 provider 工厂：Qwen ASR / Groq Whisper / 火山引擎 |
| **存储** | `b2t/storage/` | 产物持久化：本地磁盘 / MinIO (S3) / 阿里云 OSS |
| **格式转换** | `b2t/converter/` | Markdown → TXT / PDF / PNG / HTML / 表格 PDF |
| **LLM 总结** | `b2t/summarize/` | LiteLLM 流式调用，preset 模板注入，markdownlint 格式化 |
| **RAG 检索** | `b2t/rag/` | ChromaDB 向量存储，Markdown 分块，LLM 问答 + 来源引用 |
| **UP 主监控** | `b2t/monitor/` | 定时检查动态 → 自动转录 → 飞书通知 |
| **历史记录** | `b2t/history.py` | SQLite 持久化转录元数据，支持分页搜索 |
| **CLI** | `b2t/cli.py` | 命令行入口 + Textual 交互模式 |
| **Web 后端** | `web-ui/backend/` | FastAPI REST + 8 个路由模块 + 任务队列 |
| **Web 前端** | `web-ui/frontend/` | Vue 3 SPA，4 个主页面 |

## 运行时模式

| 模式 | 环境变量 | API Key 来源 | 删除功能 | 适用场景 |
|------|----------|-------------|:--:|------|
| **default** | `B2T_WEB_UI_MODE=default`（默认） | `config.toml` | ✅ | 个人使用 |
| **open-public** | `B2T_WEB_UI_MODE=open-public` | 用户在前端自行填写 | ❌ | 公开演示 / 多用户 |
