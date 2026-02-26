## bilibili-to-text

### 目录结构

- `b2t/`：核心转录流水线（下载音频 -> 语音转录 -> Markdown/TXT -> LLM 总结）
- `web-ui/`：Web 应用（FastAPI 后端 + Vue 前端）

### 文档导航

- Web 端说明与启动命令：`web-ui/README.md`

### 配置文件

CLI 与 Web UI 统一读取项目根目录配置：

- `config.toml`（参考 `config.toml.example`）
- `summary_presets.toml`（参考 `summary_presets.toml.example`）


### 环境配置

- pandoc
- playwright install chromium