# Pipeline 工作流程

## 总体流程（用户视角）

```mermaid
sequenceDiagram
    actor 用户
    participant 前端 as Vue 前端 (:6010)
    participant 后端 as FastAPI 后端 (:8000)
    participant Pipeline as run_pipeline()
    participant OSS as 阿里云 OSS
    participant ASR as DashScope ASR
    participant LLM as DeepSeek API

    用户->>前端: 输入 B站视频 URL，选择 preset
    前端->>后端: POST /api/process {url, summary_preset...}
    后端-->>前端: {job_id} (立即返回)

    Note over 后端: 线程池异步执行

    loop 前端轮询进度
        前端->>后端: GET /api/process/{job_id}
        后端-->>前端: {status, progress, stage...}
    end

    后端->>Pipeline: run_pipeline(url, config)

    Pipeline->>Pipeline: ① 下载音频 (yutto)
    Pipeline->>OSS: ② 上传音频 → 获取公网 URL
    Pipeline->>ASR: ③ 提交转写任务
    ASR-->>Pipeline: JSON 转写结果
    Pipeline->>Pipeline: ④ JSON → Markdown
    Pipeline->>LLM: ⑤ 套用 preset 模板，流式调用
    LLM-->>Pipeline: 结构化总结
    Pipeline->>OSS: ⑥ 所有产物上传 OSS

    Pipeline-->>后端: {results dict}
    后端-->>前端: {status: "succeeded", download_urls...}
    用户->>前端: 下载产物
```

## Pipeline 内部详细流程

```mermaid
flowchart TD
    START([用户输入 URL 或上传音频]) --> CHECK{audio_path?}

    CHECK -->|有本地音频| LOCAL[验证本地文件<br/>从文件名提取 BV 号]
    CHECK -->|无| DOWNLOAD[调用 yutto 下载音频<br/>extract_bvid 提取 BV 号]

    LOCAL --> WORKDIR[创建工作目录<br/>transcriptions/BVxxx_标题/]
    DOWNLOAD --> WORKDIR

    WORKDIR --> STT_STEP[步骤② 语音转文字]

    STT_STEP --> STT_TYPE{STT Provider?}

    STT_TYPE -->|Qwen ASR| QWEN[上传音频到 OSS<br/>获取临时公网 URL<br/>提交 DashScope 文件转写<br/>轮询任务状态<br/>下载转录 JSON]
    STT_TYPE -->|Groq Whisper| GROQ[本地音频分块<br/>逐块发送 Groq API<br/>合并重叠片段<br/>去重]
    STT_TYPE -->|火山引擎| VOLC[上传音频到 OSS<br/>submit → poll → result]

    QWEN --> JSON[得到 transcription.json]
    GROQ --> JSON
    VOLC --> JSON

    JSON --> MD_STEP[步骤③ JSON → Markdown]
    MD_STEP --> MD_DETAIL[解析各格式 JSON<br/>提取带时间戳句子<br/>合并短句 &lt;60 字符<br/>保存 .md 文件]

    MD_DETAIL --> SKIP{skip_summary?}

    SKIP -->|是| STORE[步骤⑤ 存储所有产物]
    SKIP -->|否| PRESET[步骤④ LLM 总结]

    PRESET --> RESOLVE[解析 preset 模板<br/>检查作者上下文 context.toml<br/>注入股票别名/主题词]
    RESOLVE --> PROMPT[构建 prompt =<br/>context_block + 转录正文 + template]
    PROMPT --> STREAM[LiteLLM 流式调用 LLM<br/>支持 bailian/deepseek/groq/openrouter]
    STREAM --> POST[后处理：降级标题<br/>注入视频元数据<br/>markdownlint 格式化]
    POST --> SAVE[保存 _summary.md]
    SAVE --> TABLE[提取末尾 Markdown 表格<br/>保存 _summary_table.md]

    TABLE --> STORE
    STORE --> OSS[上传到阿里云 OSS<br/>b2t/BVxxx-hex/filename]
    OSS --> DONE([返回 dict[str, StoredArtifact]])
```

## STT 语音转写详细流程（Qwen ASR）

```mermaid
flowchart TD
    AUDIO[/.m4a 音频文件/] --> CK_SIZE{文件大小检查}
    CK_SIZE -->|>1GB| ERR[拒绝：文件过大]
    CK_SIZE -->|ok| UPLOAD[上传到 OSS<br/>b2t/temp-audio/uuid-filename]

    UPLOAD --> URL[生成临时公网 URL<br/>供 DashScope 下载]
    URL --> SUBMIT[POST DashScope<br/>提交文件转写任务<br/>model: qwen3-asr-flash-filetrans]

    SUBMIT --> POLL[轮询任务状态<br/>间隔: 5s]
    POLL --> STATUS{状态?}
    STATUS -->|PENDING/RUNNING| POLL
    STATUS -->|SUCCEEDED| DL_JSON[下载转录 JSON]
    STATUS -->|FAILED| RETRY[重试 / 报错]

    DL_JSON --> CLEAN[删除 OSS 临时音频]
    CLEAN --> DONE_JSON[/transcription.json/]
```

## 总结 Prompt 构建流程

```mermaid
flowchart TD
    MD[/转录 Markdown/] --> READ[读取文件内容]

    META[VideoMetadata<br/>作者/标题/发布时间] --> CTX_MATCH{context.toml<br/>是否匹配到作者?}

    CTX_MATCH -->|是| CTX_INJECT[注入作者上下文<br/>股票池 / 别名映射 / 主题词]
    CTX_MATCH -->|否| SKIP_CTX[跳过上下文注入]

    CTX_INJECT --> CONTENT
    SKIP_CTX --> CONTENT

    READ --> CONTENT[合并: context_block + 转录正文]
    CONTENT --> TEMPLATE[套用 preset 模板<br/>{content} 占位符替换]

    TEMPLATE --> LLM_CALL[LiteLLM stream_completion<br/>api_base + api_key + model]
    LLM_CALL --> REASON[提取 reasoning_content<br/>（思维链输出）]
    LLM_CALL --> ANSWER[收集 content 字段]

    REASON --> LOG[打印推理过程到终端]
    ANSWER --> POST[post_process_summary_markdown:<br/>1. # 标题降级为 ##<br/>2. 添加元数据头部<br/>3. markdownlint 格式化]

    POST --> SAVE[/_summary.md/]
```

## Web 后端任务生命周期

```mermaid
stateDiagram-v2
    [*] --> queued: POST /api/process
    queued --> running: 线程池分配
    running --> downloading: 阶段1
    downloading --> transcribing: 阶段2
    transcribing --> converting: 阶段3
    converting --> summarizing: 阶段4
    summarizing --> completed: 阶段5

    running --> failed: 异常
    running --> cancelled: POST /cancel

    queued --> cancelled: POST /cancel

    completed --> [*]: 前端获取结果
    failed --> [*]: 前端获取错误信息
    cancelled --> [*]: 前端获取取消状态

    note right of completed
        产物通过
        GET /api/download/{id}
        流式下载
    end note
```

## 数据对象流转

```mermaid
flowchart LR
    subgraph 输入
        A1[B站 URL]
        A2[音频文件 .m4a/.mp3]
        A3[视频文件 .mp4]
    end

    subgraph 中间产物
        B1[.m4a 音频]
        B2[transcription.json]
        B3[transcription.md]
    end

    subgraph 最终产物
        C1[_summary.md<br/>LLM 总结]
        C2[_summary_table.md<br/>股票表格]
        C3[_summary.png<br/>截图]
        C4[_summary_fancy.html<br/>美化 HTML]
    end

    subgraph 存储
        D1[(本地磁盘)]
        D2[(MinIO)]
        D3[(阿里云 OSS)]
    end

    A1 --> B1
    A2 --> B1
    A3 -->|ffmpeg 提取音频| B1

    B1 --> B2
    B2 --> B3
    B3 --> C1
    C1 --> C2

    B1 --> D3
    B2 --> D3
    B3 --> D3
    C1 --> D3
    C2 --> D3
    C3 --> D3
    C4 --> D3
```

## RAG 检索流程

```mermaid
flowchart TD
    subgraph 索引（离线）
        IDX1[历史转录 Markdown/Summary] --> IDX2[chunk_markdown<br/>按段落分块<br/>800字符/100重叠]
        IDX2 --> IDX3[embed_texts<br/>LiteLLM 嵌入<br/>batch_size=10]
        IDX3 --> IDX4[(ChromaDB<br/>cosine 向量存储)]
    end

    subgraph 查询（在线）
        Q1[用户输入问题] --> Q2[embed_texts<br/>问题向量化]
        Q2 --> Q4[ChromaDB.query<br/>top-k 相似检索]
        Q4 --> Q5[构建 prompt:<br/>引用块 + 问题]
        Q5 --> Q6[LLM 生成回答<br/>带来源引用 [1][2]...]
        Q6 --> Q7[/RagAnswer<br/>answer + sources/]
    end

    IDX4 -.-> Q4
```
