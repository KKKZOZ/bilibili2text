# Pi 阅读报告

新建转录页的「生成阅读报告」直接读取完整转写，与 Markdown 总结独立。
转录原文保存后，两者并行执行（报告队列繁忙时需等待空位），复用历史转录时同样适用。
哪个先完成就先提供下载；某一分支失败不会中断另一分支。取消任务会同时停止两条分支。
用户仅需选择标准精读或精简速览、报告模型。
默认推理档位 high、上下文窗口 256000 tokens、最大输出 100000 tokens 由后端固定管理，不作为用户参数。
模型使用现有 API Key 页的凭证；目前适配 OpenAI Chat Completions 协议，
包括 b2t 的百炼、DeepSeek 和自定义兼容服务。服务必须支持流式工具调用。

## 安装

后端需要访问本机 Docker daemon。构建固定版本 Pi 镜像：

```bash
docker build -f docker/Dockerfile.report -t b2t-report:pi-0.85.0 docker
docker run --rm b2t-report:pi-0.85.0 --version
```

默认 `B2T_REPORT_RUNTIME=docker`，可通过 `B2T_REPORT_IMAGE` 指定同接口镜像。
默认网络为 `bridge`，管理员可通过 `config.toml` 中的 `[report] docker_network` 指定 Docker 网络，
`B2T_REPORT_NETWORK` 环境变量优先于配置文件。配置修改后重启后端。
如果当前主机的 Docker bridge DNS 不可用，可先修复 Docker 网络；个人部署也可
显式设置 `[report]` 下的 `docker_network = "host"`（或 `B2T_REPORT_NETWORK=host`）使用宿主机网络（此时没有独立网络命名空间）。
镜像构建遇到同类 DNS 问题时可使用 `docker build --network=host ...`，它只影响构建阶段。
后端以宿主机进程方式运行；如果后端本身在容器里，需使 Docker daemon 能访问
相同的任务临时目录路径。不要仅挂载 Docker socket 就假定目录映射可用。

个人开发可安装 `@earendil-works/pi-coding-agent@0.85.0`（Node.js 22），
设置 `B2T_REPORT_RUNTIME=local`。Open Public 禁止本地直接执行模式。

## 凭证与隔离

每次运行创建独立工作目录、Pi 配置目录和容器。后端生成 `models.json`，
其中仅保存 API Key 的环境变量引用；Key 通过本次子进程环境传入，不修改全局环境，
不写入命令参数、报告元数据或会话日志。未启用会话落盘。
公开请求不使用其他 provider 的管理员模型 Key。

容器只挂载本次任务目录和 Pi 配置目录，使用当前 UID/GID、只读根文件系统、
移除 capabilities，并限制为 2 CPU、2 GiB 内存、128 个进程。
它仍需联网调用用户指定的模型，默认 Docker bridge 不提供目的地址白名单；
需要限制访问内网的部署应另外配置容器出口策略。容器内的工具仍能读取本任务凭证，
这不是对工具隐藏本任务 Key 的代理架构。

## 生命周期

- 独立报告队列：2 个 worker，8 个排队位置；实际生成并发上限 2。
- 单次 Pi 执行最多 30 分钟，取消与超时会停止对应容器及子进程。
- 等待 `agent_settled` 并验证最终 assistant 的 `stopReason == stop`。
- 原文/总结先显示，报告独立失败，不覆盖已有报告，也不触发重新 ASR。
- 历史转写可直接复用；仅有旧总结且缺少原文关联时提示从新建页提交原链接。
- 临时上传报告不进入共享历史，加入原任务的到期清理列表。
- HTML 沿用 `summary_fancy_html` 产物类型和已有预览、PNG 导出入口。
  `derived_from` 指向原文，模式、模型、Skill 摘要和来源摘要写入 HTML 元数据。
- 新建 URL 任务可在不提供 DashScope Key 时复用字幕/已有转写；若回退到阿里云
  ASR，仍需要对应 Key。直接上传仍要求转写凭证。报告单独生成只检查报告模型凭证。

报告服务校验完整 HTML、模板占位符和来源 ID，并设置 CSP 禁用脚本及外部资源。
来源绑定支持逐个 ID 和完整端点的连续闭区间（例如 `u000001-u000010`，兼容 `–`、`—`），校验区间中的每个 ID，拒绝缺失单元、倒序区间和通配符。生成提示优先要求空格分隔的完整 ID，Brief 仍要求逐个列出。失败信息包含 HTML 行号、标签和具体无效引用。
当前 Pi 镜像没有浏览器，生成过程仅静态自查；没有自动浏览器修订或语义验收。
PNG 沿用 b2t 的按需 Chromium 导出，导出失败不代表 HTML 生成失败。
RAG 回答的 Fancy HTML 继续使用原有受限片段生成路径。

Skill 来自用户提供的 video-report-agent 快照，完整资产内置于
`b2t/report/skill/`，运行时无需依赖外部克隆目录，来源记录见其中的 `UPSTREAM.md`。

## 验证

```bash
uv run pytest -q tests/test_report_agent.py tests/test_report_integration.py
B2T_TEST_PI_DOCKER=1 uv run pytest -q tests/test_report_docker.py
```

第二条使用真实 Pi 容器连接本机临时模拟模型，验证两个任务的 Key/模型隔离、
工具调用和 HTML 交付，不调用真实模型、不验证报告写作质量。

报告失败会显示 Pi 结束原因及脱敏后的服务端错误。`length` 表示输出达到上限；
连接错误需检查容器网络和 DNS；401/402 等状态应按模型服务商的提示处理。

Pi 的阶段、工具执行和重试事件实时加入当前任务的执行日志；长时间等待时每 15 秒更新状态。
日志显示文件路径、读取行数、Shell 命令、工具返回摘要和模型文字回复。写入或编辑仅显示路径与字符数；
单条日志最多展示 1400 字符，过滤凭证、URL 和模型思考内容。

历史详情页提供独立的「生成阅读报告」入口，可选择模式与模型，无需先生成普通总结。
默认模型读取 `[fancy_html].profile`；报告在后台生成，完成后自动更新文件列表，失败后可重试。
