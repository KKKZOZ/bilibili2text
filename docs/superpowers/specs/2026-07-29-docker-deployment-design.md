# Docker 部署设计

## 目标

为 bilibili-to-text 提供完整、可重复的一键 Docker Compose 部署。部署包含 Vue 前端、Nginx 反向代理和 FastAPI 后端；继续使用已有的阿里云 OSS，不在 Compose 内启动 MinIO。

部署必须将运行配置和本地状态持久化到宿主机，使镜像或容器更新后仍保留转录产物、SQLite 数据和 Chroma 向量索引。

## 范围

本次交付包括：

- 一个多阶段 `Dockerfile`：构建 Vue/Vite 前端，并构建包含 Python 3.12、`ffmpeg`、`pandoc` 与 Playwright Chromium 的后端运行环境。
- 一个 `docker-compose.yml`：编排 `backend` 和 `frontend` 两个服务，使用服务名进行内部通信。
- 面向容器内部服务发现的 Nginx 配置，代理 `/api/` 至 `backend:8000`。
- 通过 Compose 环境变量配置前端暴露端口、Web UI 模式与镜像标签。
- 持久化挂载 `config.toml`、`summary_presets.toml`、`context.toml`、`transcriptions`、`db_data` 与 `chroma_data`。
- README 中的部署、更新、日志、停止和备份说明。
- 对 Compose 配置、镜像构建和 HTTP 健康检查的验证。

不包含 MinIO、数据库服务、镜像仓库发布、HTTPS 证书或反向代理网关。这些能力可由现有阿里云 OSS 和部署环境外围设施提供。

## 架构

```text
浏览器
  |
  v
frontend（Nginx，宿主机端口 ${B2T_FRONTEND_PORT:-6010}）
  |-- 静态文件：Vue/Vite 构建产物
  `-- /api/* --> backend:8000
                    |
                    |-- config.toml、summary_presets.toml、context.toml（只读挂载，阿里云 OSS 凭证与应用配置）
                    |-- transcriptions/（读写挂载）
                    |-- db_data/（读写挂载）
                    `-- chroma_data/（读写挂载）
```

`frontend` 仅负责 HTTP 静态资源和 API 反向代理；`backend` 仅运行 Uvicorn/FastAPI。服务职责相互独立，Compose 网络负责名称解析，宿主机不暴露后端端口。

## 镜像与运行时

多阶段 Dockerfile 分为前端构建阶段与后端运行阶段：

1. 前端阶段使用 Bun 安装锁定依赖并执行 `bun run build`，只将 `dist` 复制到 Nginx 镜像。
2. 后端阶段基于 Python 3.12 slim，安装运行所需系统包：`ffmpeg`、`pandoc` 和 Playwright Chromium 所需依赖。
3. 使用 `uv` 按 `uv.lock` 安装 Python 的 `web` 可选依赖；将项目源码与必要配置模板复制到运行镜像。
4. 安装 Playwright Chromium，确保 PDF/PNG 转换在容器内可用。
5. 后端以非 root 用户运行 Uvicorn，监听 `0.0.0.0:8000`，使用单 worker 以兼容进程内任务队列与本地状态。

容器不会把 API 密钥写入镜像层；密钥仍保存在宿主机的 `config.toml`，并通过只读绑定挂载提供给后端。

## Compose 接口

`docker-compose.yml` 使用如下可覆盖变量：

| 变量 | 默认值 | 用途 |
| --- | --- | --- |
| `B2T_IMAGE_TAG` | `local` | 两个应用镜像的标签 |
| `B2T_FRONTEND_PORT` | `6010` | 前端对宿主机开放的端口 |
| `B2T_WEB_UI_MODE` | `default` | Web UI 运行模式；可设为 `open-public` |
| `B2T_CONFIG_PATH` | `./config.toml` | 宿主机配置文件路径 |
| `B2T_SUMMARY_PRESETS_PATH` | `./summary_presets.toml` | 宿主机总结预设配置文件路径 |
| `B2T_CONTEXT_PATH` | `./context.toml` | 宿主机术语上下文配置文件路径 |
| `B2T_TRANSCRIPTIONS_DIR` | `./transcriptions` | 宿主机转录产物目录 |
| `B2T_DB_DIR` | `./db_data` | 宿主机 SQLite 数据目录 |
| `B2T_CHROMA_DIR` | `./chroma_data` | 宿主机 Chroma 数据目录 |

`backend` 使用 `/app/config.toml`、`/app/summary_presets.toml`、`/app/context.toml`、`/app/transcriptions`、`/app/db_data` 和 `/app/chroma_data` 作为固定容器内路径。`frontend` 的 `depends_on` 以 backend 健康检查为条件，避免页面服务在 API 尚未可用时启动。

## 健康检查与故障行为

后端健康检查访问已有的健康 API；失败时 Docker 根据 `restart: unless-stopped` 重启服务。前端同样使用 HTTP 健康检查确认 Nginx 可响应。后端不可用时，Nginx 对 API 请求返回网关错误而不会影响静态页面加载。

运行时日志输出至标准输出，运维人员通过 `docker compose logs -f backend` 或 `docker compose logs -f frontend` 查看。转录任务、数据库和向量数据不写入容器可写层，因而可安全重建应用容器。

## 使用流程

1. 复制并完善 `config.toml`，保留其中已配置的阿里云 OSS 凭证。
2. 可选创建 `.env` 覆盖端口、模式或数据目录。
3. 执行 `docker compose up -d --build`。
4. 访问 `http://<host>:6010`；使用 `docker compose ps` 和健康接口确认服务可用。
5. 更新时执行 `docker compose up -d --build`；停止使用 `docker compose down`。该命令不会删除宿主机绑定的数据目录。
6. 备份时停止后端写入或短暂停机，然后备份所有挂载目标，尤其是 `db_data` 和 `chroma_data`。

## 验收与测试

- `docker compose config` 能无错误渲染配置，并解析出两个服务、正确端口和四项挂载。
- `docker compose build` 能完成前端和后端镜像构建。
- `docker compose up -d` 后，backend 健康检查通过。
- 经由前端公开端口请求 `/api/health` 能得到成功响应，验证 Nginx 代理链路。
- 创建或保留的测试数据在 `docker compose down` 后再次 `up` 仍可读取，验证绑定挂载的持久化。
- README 提供不依赖 MinIO 的完整操作说明，并明确 `config.toml` 含敏感凭证、不可提交。
