"""FastAPI service for bilibili-to-text."""

from collections import OrderedDict
from datetime import datetime, timezone
import logging
from pathlib import Path
import re
from threading import Lock, Thread, get_ident
import time
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from b2t.config import AppConfig, load_config, resolve_summary_preset_name
from b2t.pipeline import run_pipeline

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
JOB_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
JOB_LOG_DATE_FORMAT = "%H:%M:%S"
JOB_LOG_LIMIT = 400
STAGE_KEYS = (
    "queued",
    "downloading",
    "transcribing",
    "converting",
    "summarizing",
    "completed",
)

JobValue = (
    str
    | int
    | float
    | bool
    | None
    | list[str]
    | dict[str, int]
    | dict[str, bool]
    | dict[str, str]
)

_URL_PATTERN = re.compile(r"https?://[^\s\"']+")
_OSS_OBJECT_KEY_PATTERN = re.compile(r"(temp-audio/)[^\s\"']+")
_SECRET_PATTERN = re.compile(
    r"(?i)\b(access[_-]?key(?:[_-]?(?:id|secret))?|api[_-]?key|token|secret)\b\s*[:=]\s*[^,\s]+"
)


def _redact_text(message: str) -> str:
    sanitized = _URL_PATTERN.sub("[REDACTED_URL]", message)
    sanitized = _OSS_OBJECT_KEY_PATTERN.sub(r"\1[REDACTED_OBJECT_KEY]", sanitized)
    sanitized = _SECRET_PATTERN.sub(r"\1=[REDACTED]", sanitized)
    return sanitized


class _SensitiveDataFilter(logging.Filter):
    """在日志输出前统一脱敏，确保日志源头就是安全内容。"""

    def filter(self, record: logging.LogRecord) -> bool:
        original = record.getMessage()
        sanitized = _redact_text(original)
        if sanitized != original:
            record.msg = sanitized
            record.args = ()
        return True


_SENSITIVE_DATA_FILTER = _SensitiveDataFilter()


def _format_elapsed(seconds: int) -> str:
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _snapshot_stage_durations(job: dict[str, JobValue]) -> dict[str, int]:
    snapshot: dict[str, int] = {key: 0 for key in STAGE_KEYS}
    stored = job.get("stage_durations_seconds")
    if isinstance(stored, dict):
        for key in STAGE_KEYS:
            value = stored.get(key)
            if isinstance(value, int):
                snapshot[key] = max(0, value)

    current_stage = str(job.get("stage") or "")
    status = str(job.get("status") or "")
    started_at = job.get("stage_started_monotonic")
    if (
        current_stage in snapshot
        and status in {"queued", "running"}
        and isinstance(started_at, (int, float))
    ):
        snapshot[current_stage] += max(0, int(time.monotonic() - float(started_at)))

    return snapshot


def _build_stage_duration_labels(job: dict[str, JobValue]) -> dict[str, str]:
    durations = _snapshot_stage_durations(job)
    seen = job.get("stage_seen")
    seen_map: dict[str, bool] = {key: False for key in STAGE_KEYS}
    if isinstance(seen, dict):
        for key in STAGE_KEYS:
            value = seen.get(key)
            if isinstance(value, bool):
                seen_map[key] = value

    current_stage = str(job.get("stage") or "")
    skip_summary = bool(job.get("skip_summary"))

    labels: dict[str, str] = {}
    for key in STAGE_KEYS:
        if skip_summary and key == "summarizing":
            labels[key] = "跳过"
            continue

        has_started = seen_map.get(key, False) or key == current_stage
        if has_started or durations[key] > 0:
            labels[key] = _format_elapsed(durations[key])
        else:
            labels[key] = "--"
    return labels


class _JobLogHandler(logging.Handler):
    def __init__(self, job_id: str, thread_id: int) -> None:
        super().__init__(level=logging.INFO)
        self._job_id = job_id
        self._thread_id = thread_id
        self.setFormatter(
            logging.Formatter(fmt=JOB_LOG_FORMAT, datefmt=JOB_LOG_DATE_FORMAT)
        )
        self.addFilter(_SENSITIVE_DATA_FILTER)

    def emit(self, record: logging.LogRecord) -> None:
        if record.thread != self._thread_id:
            return

        logger_name = record.name
        if not (
            logger_name == "b2t"
            or logger_name.startswith("b2t.")
            or logger_name in {"dashscope", "httpx"}
        ):
            return

        try:
            line = self.format(record)
        except Exception:
            self.handleError(record)
            return

        _append_job_log(self._job_id, line)


def _configure_logging() -> None:
    """统一后端日志格式，包含到秒级时间戳。"""
    formatter = logging.Formatter(fmt=LOG_FORMAT, datefmt=LOG_DATE_FORMAT)
    for logger_name in ("", "uvicorn", "uvicorn.error", "uvicorn.access"):
        target_logger = logging.getLogger(logger_name)
        for handler in target_logger.handlers:
            handler.setFormatter(formatter)
            if not any(
                isinstance(filter_obj, _SensitiveDataFilter)
                for filter_obj in handler.filters
            ):
                handler.addFilter(_SENSITIVE_DATA_FILTER)

    # 任务日志面板依赖 INFO 级别日志；这些 logger 默认可能继承到 WARNING。
    logging.getLogger("b2t").setLevel(logging.INFO)
    logging.getLogger("dashscope").setLevel(logging.INFO)
    logging.getLogger("httpx").setLevel(logging.INFO)


class ProcessRequest(BaseModel):
    url: str = Field(..., min_length=1, description="Bilibili 视频 URL")
    skip_summary: bool = Field(
        default=False,
        description="是否跳过总结步骤",
    )
    summary_preset: str | None = Field(
        default=None,
        description="总结 preset 名称",
    )


class ProcessStartResponse(BaseModel):
    job_id: str


class ProcessStatusResponse(BaseModel):
    job_id: str
    status: Literal["queued", "running", "succeeded", "failed"]
    stage: str
    stage_label: str
    progress: int = Field(ge=0, le=100)
    download_url: str
    filename: str | None = None
    summary_download_url: str | None = None
    summary_filename: str | None = None
    summary_preset: str | None = None
    error: str | None = None
    logs: list[str] = Field(default_factory=list)
    stage_durations: dict[str, str] = Field(default_factory=dict)
    created_at: str
    updated_at: str


class SummaryPresetItemResponse(BaseModel):
    name: str
    label: str


class SummaryPresetListResponse(BaseModel):
    default_preset: str
    selected_preset: str
    presets: list[SummaryPresetItemResponse]


app = FastAPI(title="bilibili-to-text API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_download_index: OrderedDict[str, Path] = OrderedDict()
_download_lock = Lock()
_download_limit = 100

_job_index: OrderedDict[str, dict[str, JobValue]] = OrderedDict()
_job_lock = Lock()
_job_limit = 200

try:
    _app_config: AppConfig | None = load_config()
except FileNotFoundError:
    _app_config = None


@app.on_event("startup")
def on_startup() -> None:
    _configure_logging()


def _store_download(path: Path) -> str:
    download_id = uuid4().hex
    resolved_path = path.resolve()

    with _download_lock:
        _download_index[download_id] = resolved_path
        while len(_download_index) > _download_limit:
            _download_index.popitem(last=False)

    return download_id


def _utc_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _create_job(
    *,
    skip_summary: bool,
    summary_preset: str | None,
) -> dict[str, JobValue]:
    now = _utc_iso()
    job_id = uuid4().hex
    job: dict[str, JobValue] = {
        "job_id": job_id,
        "status": "queued",
        "stage": "queued",
        "stage_label": "任务已创建，等待开始",
        "progress": 0,
        "download_url": "",
        "filename": None,
        "summary_download_url": None,
        "summary_filename": None,
        "error": None,
        "created_at": now,
        "updated_at": now,
        "skip_summary": skip_summary,
        "summary_preset": summary_preset,
        "logs": [],
        "stage_started_monotonic": time.monotonic(),
        "stage_durations_seconds": {key: 0 for key in STAGE_KEYS},
        "stage_seen": {key: key == "queued" for key in STAGE_KEYS},
    }

    with _job_lock:
        _job_index[job_id] = job
        while len(_job_index) > _job_limit:
            _job_index.popitem(last=False)

    return job


def _update_job(
    job_id: str,
    *,
    status: str | None = None,
    stage: str | None = None,
    stage_label: str | None = None,
    progress: int | None = None,
    error: str | None = None,
    download_url: str | None = None,
    filename: str | None = None,
    summary_download_url: str | None = None,
    summary_filename: str | None = None,
) -> None:
    with _job_lock:
        job = _job_index.get(job_id)
        if job is None:
            return

        now_mono = time.monotonic()
        current_stage = str(job.get("stage") or "")
        next_stage = stage if stage is not None else current_stage
        durations = job.get("stage_durations_seconds")
        if not isinstance(durations, dict):
            durations = {key: 0 for key in STAGE_KEYS}
            job["stage_durations_seconds"] = durations

        seen = job.get("stage_seen")
        if not isinstance(seen, dict):
            seen = {key: key == "queued" for key in STAGE_KEYS}
            job["stage_seen"] = seen

        if (
            stage is not None
            and current_stage in STAGE_KEYS
            and next_stage != current_stage
            and isinstance(job.get("stage_started_monotonic"), (int, float))
        ):
            elapsed = max(
                0,
                int(now_mono - float(job["stage_started_monotonic"])),
            )
            previous = durations.get(current_stage)
            previous_elapsed = previous if isinstance(previous, int) else 0
            durations[current_stage] = previous_elapsed + elapsed
            job["stage_started_monotonic"] = now_mono

        if stage is not None and stage in STAGE_KEYS:
            seen[stage] = True

        if status is not None:
            job["status"] = status
        if stage is not None:
            job["stage"] = stage
        if stage_label is not None:
            job["stage_label"] = stage_label
        if progress is not None:
            job["progress"] = max(0, min(100, progress))
        if error is not None:
            job["error"] = error
        if download_url is not None:
            job["download_url"] = download_url
        if filename is not None:
            job["filename"] = filename
        if summary_download_url is not None:
            job["summary_download_url"] = summary_download_url
        if summary_filename is not None:
            job["summary_filename"] = summary_filename

        job["updated_at"] = _utc_iso()


def _append_job_log(job_id: str, line: str) -> None:
    with _job_lock:
        job = _job_index.get(job_id)
        if job is None:
            return

        logs = job.get("logs")
        if not isinstance(logs, list):
            logs = []
            job["logs"] = logs

        logs.append(line)
        if len(logs) > JOB_LOG_LIMIT:
            del logs[:-JOB_LOG_LIMIT]

        job["updated_at"] = _utc_iso()


def _get_job(job_id: str) -> dict[str, JobValue] | None:
    with _job_lock:
        job = _job_index.get(job_id)
        if job is None:
            return None

        payload = dict(job)
        logs = job.get("logs")
        if isinstance(logs, list):
            payload["logs"] = list(logs)
        payload["stage_durations"] = _build_stage_duration_labels(job)
        return payload


def _get_app_config() -> AppConfig:
    global _app_config
    if _app_config is not None:
        return _app_config

    _app_config = load_config()
    return _app_config


def _run_job(
    job_id: str,
    *,
    url: str,
    skip_summary: bool,
    summary_preset: str | None,
) -> None:
    try:
        config = _get_app_config()
    except FileNotFoundError:
        _update_job(
            job_id,
            status="failed",
            stage="failed",
            stage_label="处理失败",
            progress=0,
            error="配置文件不存在，请先在项目根目录创建 config.toml",
        )
        _append_job_log(
            job_id,
            f"{datetime.now().strftime(JOB_LOG_DATE_FORMAT)} [ERROR] b2t.pipeline: 配置文件不存在，请先在项目根目录创建 config.toml",
        )
        return

    log_handler = _JobLogHandler(job_id=job_id, thread_id=get_ident())
    root_logger = logging.getLogger()
    root_logger.addHandler(log_handler)

    _update_job(
        job_id,
        status="running",
        stage="queued",
        stage_label="开始处理任务",
        progress=5,
    )

    try:
        try:
            results = run_pipeline(
                url,
                config,
                skip_summary=skip_summary,
                summary_preset=summary_preset,
                progress_callback=lambda stage, label, progress: _update_job(
                    job_id,
                    status="running",
                    stage=stage,
                    stage_label=label,
                    progress=progress,
                ),
            )
        except Exception as exc:
            _update_job(
                job_id,
                status="failed",
                stage="failed",
                stage_label="处理失败",
                error=str(exc),
            )
            _append_job_log(
                job_id,
                f"{datetime.now().strftime(JOB_LOG_DATE_FORMAT)} [ERROR] b2t.pipeline: {_redact_text(str(exc))}",
            )
            return

        md_path = results.get("markdown")
        if md_path is None:
            _update_job(
                job_id,
                status="failed",
                stage="failed",
                stage_label="处理失败",
                error="未生成 Markdown 文件",
            )
            _append_job_log(
                job_id,
                f"{datetime.now().strftime(JOB_LOG_DATE_FORMAT)} [ERROR] b2t.pipeline: 未生成 Markdown 文件",
            )
            return

        download_id = _store_download(md_path)

        summary_download_url: str | None = None
        summary_filename: str | None = None
        summary_path = results.get("summary")
        if summary_path is not None:
            summary_download_id = _store_download(summary_path)
            summary_download_url = f"/api/download/{summary_download_id}"
            summary_filename = summary_path.name

        _update_job(
            job_id,
            status="succeeded",
            stage="completed",
            stage_label="处理完成",
            progress=100,
            download_url=f"/api/download/{download_id}",
            filename=md_path.name,
            summary_download_url=summary_download_url,
            summary_filename=summary_filename,
            error=None,
        )
    finally:
        root_logger.removeHandler(log_handler)
        log_handler.close()


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/process", response_model=ProcessStartResponse)
def process_video(payload: ProcessRequest) -> ProcessStartResponse:
    if not payload.url.strip():
        raise HTTPException(status_code=400, detail="URL 不能为空")

    summary_preset = (
        payload.summary_preset.strip() if payload.summary_preset else None
    )
    if summary_preset == "":
        summary_preset = None

    job = _create_job(
        skip_summary=payload.skip_summary,
        summary_preset=summary_preset,
    )
    Thread(
        target=_run_job,
        kwargs={
            "job_id": str(job["job_id"]),
            "url": payload.url.strip(),
            "skip_summary": payload.skip_summary,
            "summary_preset": summary_preset,
        },
        daemon=True,
    ).start()

    return ProcessStartResponse(job_id=str(job["job_id"]))


@app.get("/api/process/{job_id}", response_model=ProcessStatusResponse)
def process_status(job_id: str) -> ProcessStatusResponse:
    job = _get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在或已过期")

    return ProcessStatusResponse(
        job_id=str(job["job_id"]),
        status=str(job["status"]),
        stage=str(job["stage"]),
        stage_label=str(job["stage_label"]),
        progress=int(job["progress"]),
        download_url=str(job["download_url"]),
        filename=job["filename"] if isinstance(job["filename"], str) else None,
        summary_download_url=job["summary_download_url"]
        if isinstance(job["summary_download_url"], str)
        else None,
        summary_filename=job["summary_filename"]
        if isinstance(job["summary_filename"], str)
        else None,
        summary_preset=job["summary_preset"]
        if isinstance(job["summary_preset"], str)
        else None,
        error=job["error"] if isinstance(job["error"], str) else None,
        logs=job["logs"] if isinstance(job["logs"], list) else [],
        stage_durations=job["stage_durations"]
        if isinstance(job["stage_durations"], dict)
        else {},
        created_at=str(job["created_at"]),
        updated_at=str(job["updated_at"]),
    )


@app.get("/api/summary-presets", response_model=SummaryPresetListResponse)
def summary_presets() -> SummaryPresetListResponse:
    try:
        config = _get_app_config()
    except FileNotFoundError:
        raise HTTPException(
            status_code=503,
            detail="配置文件不存在，请先在项目根目录创建 config.toml",
        ) from None

    try:
        selected = resolve_summary_preset_name(
            polish=config.polish,
            summary_presets=config.summary_presets,
            override=config.polish.preset,
        )
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    presets = [
        SummaryPresetItemResponse(name=name, label=preset.label)
        for name, preset in config.summary_presets.presets.items()
    ]

    return SummaryPresetListResponse(
        default_preset=config.summary_presets.default,
        selected_preset=selected,
        presets=presets,
    )


@app.get("/api/download/{download_id}")
def download_markdown(download_id: str) -> FileResponse:
    with _download_lock:
        md_path = _download_index.get(download_id)

    if md_path is None:
        raise HTTPException(status_code=404, detail="下载链接不存在或已过期")

    if not md_path.exists() or not md_path.is_file():
        raise HTTPException(status_code=410, detail="文件不存在，请重新生成")

    return FileResponse(
        path=md_path,
        media_type="text/markdown; charset=utf-8",
        filename=md_path.name,
    )
