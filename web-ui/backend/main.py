"""FastAPI service for bilibili-to-text."""

from collections import OrderedDict
from datetime import datetime, timezone
import logging
from pathlib import Path
import re
import tempfile
import sys
from threading import Lock, Thread, get_ident
import time
from typing import Literal, Mapping
from urllib.parse import quote
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

# Ensure `b2t` imports work when starting uvicorn from `web-ui/`.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
_ROOT_CONFIG_PATH = _PROJECT_ROOT / "config.toml"

from b2t.config import (
    AppConfig,
    load_config,
    resolve_summarize_model_profile,
    resolve_summary_preset_name,
)
from b2t.converter.converter import ConversionFormat, convert_file
from b2t.converter.md_to_txt import convert_md_to_txt
from b2t.download.yutto_cli import extract_bvid
from b2t.history import HistoryDB, record_pipeline_run
from b2t.pipeline import run_pipeline
from b2t.storage import StorageBackend, StoredArtifact, create_storage_backend
from b2t.storage.base import classify_artifact_filename
from b2t.summarize.llm import (
    export_summary_table_markdown,
    export_summary_table_pdf,
    summarize,
)

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
    | list[dict[str, str]]
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
    summary_profile: str | None = Field(
        default=None,
        description="总结模型 profile 名称",
    )


class ProcessStartResponse(BaseModel):
    job_id: str


class DownloadItemResponse(BaseModel):
    url: str
    filename: str
    kind: str


class ProcessStatusResponse(BaseModel):
    job_id: str
    status: Literal["queued", "running", "succeeded", "failed"]
    stage: str
    stage_label: str
    progress: int = Field(ge=0, le=100)
    download_url: str
    filename: str | None = None
    txt_download_url: str | None = None
    txt_filename: str | None = None
    summary_download_url: str | None = None
    summary_filename: str | None = None
    summary_txt_download_url: str | None = None
    summary_txt_filename: str | None = None
    summary_table_pdf_download_url: str | None = None
    summary_table_pdf_filename: str | None = None
    summary_preset: str | None = None
    summary_profile: str | None = None
    already_transcribed: bool = False
    notice: str | None = None
    all_downloads: list[DownloadItemResponse] = Field(default_factory=list)
    error: str | None = None
    logs: list[str] = Field(default_factory=list)
    stage_durations: dict[str, str] = Field(default_factory=dict)
    created_at: str
    updated_at: str
    author: str | None = None
    pubdate: str | None = None
    bvid: str | None = None


class SummaryPresetItemResponse(BaseModel):
    name: str
    label: str


class SummaryPresetListResponse(BaseModel):
    default_preset: str
    selected_preset: str
    presets: list[SummaryPresetItemResponse]


class SummaryProfileItemResponse(BaseModel):
    name: str
    model: str
    endpoint: str


class SummaryProfileListResponse(BaseModel):
    default_profile: str
    selected_profile: str
    profiles: list[SummaryProfileItemResponse]


class HistoryItemResponse(BaseModel):
    run_id: str
    bvid: str
    title: str
    author: str
    pubdate: str
    created_at: str
    has_summary: bool
    file_count: int


class HistoryListResponse(BaseModel):
    items: list[HistoryItemResponse]
    total: int
    page: int
    page_size: int
    has_more: bool


class HistoryDetailArtifactResponse(BaseModel):
    kind: str
    filename: str
    download_url: str


class HistoryDetailResponse(BaseModel):
    run_id: str
    bvid: str
    title: str
    author: str
    pubdate: str
    created_at: str
    has_summary: bool
    artifacts: list[HistoryDetailArtifactResponse]


class ConvertRequest(BaseModel):
    download_id: str = Field(..., description="下载 ID（来自 all_downloads 或 history 详情）")
    target_format: str = Field(..., description="目标格式：txt, pdf, png, html")


class ConvertResponse(BaseModel):
    download_url: str
    filename: str


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

logger = logging.getLogger(__name__)

_download_index: OrderedDict[str, StoredArtifact] = OrderedDict()
_download_lock = Lock()
_download_limit = 100

_job_index: OrderedDict[str, dict[str, JobValue]] = OrderedDict()
_job_lock = Lock()
_job_limit = 200
_storage_backend: StorageBackend | None = None
_history_db: HistoryDB | None = None

try:
    _app_config: AppConfig | None = load_config(_ROOT_CONFIG_PATH)
except FileNotFoundError:
    _app_config = None


@app.on_event("startup")
def on_startup() -> None:
    _configure_logging()


def _get_storage_backend() -> StorageBackend:
    global _storage_backend
    if _storage_backend is not None:
        return _storage_backend

    _storage_backend = create_storage_backend(_get_app_config())
    return _storage_backend


def _get_history_db() -> HistoryDB:
    global _history_db
    if _history_db is not None:
        return _history_db

    config = _get_app_config()
    db_dir = config.download.db_dir
    _history_db = HistoryDB(db_dir)
    return _history_db


def _store_download(artifact: StoredArtifact) -> str:
    download_id = uuid4().hex

    with _download_lock:
        _download_index[download_id] = artifact
        while len(_download_index) > _download_limit:
            _download_index.popitem(last=False)

    return download_id


def _utc_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _create_job(
    *,
    skip_summary: bool,
    summary_preset: str | None,
    summary_profile: str | None,
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
        "txt_download_url": None,
        "txt_filename": None,
        "summary_download_url": None,
        "summary_filename": None,
        "summary_txt_download_url": None,
        "summary_txt_filename": None,
        "summary_table_pdf_download_url": None,
        "summary_table_pdf_filename": None,
        "already_transcribed": False,
        "notice": None,
        "all_downloads": [],
        "error": None,
        "created_at": now,
        "updated_at": now,
        "skip_summary": skip_summary,
        "summary_preset": summary_preset,
        "summary_profile": summary_profile,
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
    txt_download_url: str | None = None,
    txt_filename: str | None = None,
    summary_download_url: str | None = None,
    summary_filename: str | None = None,
    summary_txt_download_url: str | None = None,
    summary_txt_filename: str | None = None,
    summary_table_pdf_download_url: str | None = None,
    summary_table_pdf_filename: str | None = None,
    already_transcribed: bool | None = None,
    notice: str | None = None,
    all_downloads: list[dict[str, str]] | None = None,
    author: str | None = None,
    pubdate: str | None = None,
    bvid: str | None = None,
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
        if txt_download_url is not None:
            job["txt_download_url"] = txt_download_url
        if txt_filename is not None:
            job["txt_filename"] = txt_filename
        if summary_download_url is not None:
            job["summary_download_url"] = summary_download_url
        if summary_filename is not None:
            job["summary_filename"] = summary_filename
        if summary_txt_download_url is not None:
            job["summary_txt_download_url"] = summary_txt_download_url
        if summary_txt_filename is not None:
            job["summary_txt_filename"] = summary_txt_filename
        if summary_table_pdf_download_url is not None:
            job["summary_table_pdf_download_url"] = summary_table_pdf_download_url
        if summary_table_pdf_filename is not None:
            job["summary_table_pdf_filename"] = summary_table_pdf_filename
        if already_transcribed is not None:
            job["already_transcribed"] = already_transcribed
        if notice is not None:
            job["notice"] = notice
        if all_downloads is not None:
            job["all_downloads"] = all_downloads
        if author is not None:
            job["author"] = author
        if pubdate is not None:
            job["pubdate"] = pubdate
        if bvid is not None:
            job["bvid"] = bvid

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

    _app_config = load_config(_ROOT_CONFIG_PATH)
    return _app_config


def _build_success_download_fields(
    results: dict[str, StoredArtifact],
) -> dict[str, str | None]:
    md_artifact = results.get("markdown")
    if md_artifact is None:
        raise ValueError("未生成 Markdown 文件")

    payload: dict[str, str | None] = {
        "download_url": f"/api/download/{_store_download(md_artifact)}",
        "filename": md_artifact.filename,
        "txt_download_url": None,
        "txt_filename": None,
        "summary_download_url": None,
        "summary_filename": None,
        "summary_txt_download_url": None,
        "summary_txt_filename": None,
        "summary_table_pdf_download_url": None,
        "summary_table_pdf_filename": None,
    }

    txt_artifact = results.get("text")
    if txt_artifact is not None:
        payload["txt_download_url"] = f"/api/download/{_store_download(txt_artifact)}"
        payload["txt_filename"] = txt_artifact.filename

    summary_artifact = results.get("summary")
    if summary_artifact is not None:
        payload["summary_download_url"] = (
            f"/api/download/{_store_download(summary_artifact)}"
        )
        payload["summary_filename"] = summary_artifact.filename

    summary_txt_artifact = results.get("summary_text")
    if summary_txt_artifact is not None:
        payload["summary_txt_download_url"] = (
            f"/api/download/{_store_download(summary_txt_artifact)}"
        )
        payload["summary_txt_filename"] = summary_txt_artifact.filename

    summary_table_pdf_artifact = results.get("summary_table_pdf")
    if summary_table_pdf_artifact is not None:
        payload["summary_table_pdf_download_url"] = (
            f"/api/download/{_store_download(summary_table_pdf_artifact)}"
        )
        payload["summary_table_pdf_filename"] = summary_table_pdf_artifact.filename

    return payload


def _build_all_download_items(
    artifacts: list[StoredArtifact],
) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    seen_keys: set[str] = set()
    for artifact in artifacts:
        if artifact.storage_key in seen_keys:
            continue
        seen_keys.add(artifact.storage_key)

        download_id = _store_download(artifact)
        kind = classify_artifact_filename(artifact.filename) or "file"
        items.append(
            {
                "url": f"/api/download/{download_id}",
                "filename": artifact.filename,
                "kind": kind,
            }
        )
    return items


def _collect_all_artifacts_for_bvid(
    storage_backend: StorageBackend,
    bvid: str | None,
    fallback_results: Mapping[str, object],
) -> list[StoredArtifact]:
    fallback_artifacts = [
        artifact
        for key, artifact in fallback_results.items()
        if not key.startswith("_") and isinstance(artifact, StoredArtifact)
    ]

    def _merge_with_fallback(
        listed: list[StoredArtifact],
    ) -> list[StoredArtifact]:
        merged: list[StoredArtifact] = []
        seen_keys: set[str] = set()
        for artifact in listed:
            if artifact.storage_key in seen_keys:
                continue
            seen_keys.add(artifact.storage_key)
            merged.append(artifact)
        for artifact in fallback_artifacts:
            if artifact.storage_key in seen_keys:
                continue
            seen_keys.add(artifact.storage_key)
            merged.append(artifact)
        return merged

    if bvid is None:
        return fallback_artifacts
    try:
        artifacts = storage_backend.list_existing_transcription_artifacts(bvid)
    except Exception as exc:
        logger.warning("查询 %s 的历史文件失败: %s", bvid, exc)
        return fallback_artifacts
    if artifacts:
        return _merge_with_fallback(artifacts)
    return fallback_artifacts


def _materialize_artifact_to_file(
    storage_backend: StorageBackend,
    artifact: StoredArtifact,
    target_dir: Path,
) -> Path:
    target_path = target_dir / artifact.filename
    with storage_backend.open_stream(artifact.storage_key) as stream:
        with target_path.open("wb") as output:
            while True:
                chunk = stream.read(1024 * 1024)
                if not chunk:
                    break
                output.write(chunk)
    return target_path


def _run_summary_only_from_existing(
    *,
    bvid: str,
    storage_backend: StorageBackend,
    config: AppConfig,
    existing_results: dict[str, StoredArtifact],
    summary_preset: str | None,
    summary_profile: str | None,
) -> dict[str, StoredArtifact]:
    markdown_artifact = existing_results.get("markdown")
    if markdown_artifact is None:
        raise ValueError("历史转录结果中缺少 Markdown 文件，无法仅执行总结步骤")

    run_prefix = f"{bvid}-{uuid4().hex[:8]}"
    cleanup_temp_dir: tempfile.TemporaryDirectory | None = None
    if storage_backend.persist_local_outputs:
        work_root = Path(config.download.output_dir).expanduser().resolve()
        work_root.mkdir(parents=True, exist_ok=True)
        work_dir = work_root / run_prefix
        work_dir.mkdir(parents=True, exist_ok=False)
    else:
        cleanup_temp_dir = tempfile.TemporaryDirectory(prefix="b2t-summary-")
        work_dir = Path(cleanup_temp_dir.name)

    try:
        markdown_path = _materialize_artifact_to_file(
            storage_backend,
            markdown_artifact,
            work_dir,
        )

        summary_path = summarize(
            markdown_path,
            config.summarize,
            config.summary_presets,
            preset=summary_preset,
            profile=summary_profile,
        )
        summary_text_path = convert_md_to_txt(summary_path)

        summary_table_md: Path | None = None
        summary_table_pdf: Path | None = None
        try:
            summary_table_md = export_summary_table_markdown(summary_path, which="last")
        except Exception as exc:
            logger.warning("总结表格 Markdown 导出失败，已跳过: %s", exc)
        try:
            summary_table_pdf = export_summary_table_pdf(summary_path, which="last")
        except Exception as exc:
            logger.warning("总结表格 PDF 导出失败，已跳过: %s", exc)

        results: dict[str, StoredArtifact] = {}
        results["summary"] = storage_backend.store_file(
            summary_path,
            object_key=f"{run_prefix}/{summary_path.name}",
        )
        results["summary_text"] = storage_backend.store_file(
            summary_text_path,
            object_key=f"{run_prefix}/{summary_text_path.name}",
        )
        if summary_table_md is not None:
            results["summary_table_md"] = storage_backend.store_file(
                summary_table_md,
                object_key=f"{run_prefix}/{summary_table_md.name}",
            )
        if summary_table_pdf is not None:
            results["summary_table_pdf"] = storage_backend.store_file(
                summary_table_pdf,
                object_key=f"{run_prefix}/{summary_table_pdf.name}",
            )

        # local backend 仅为总结临时拷贝 markdown，避免污染历史文件列表。
        if storage_backend.persist_local_outputs:
            markdown_path.unlink(missing_ok=True)

        return results
    finally:
        if cleanup_temp_dir is not None:
            cleanup_temp_dir.cleanup()


def _record_history(
    *,
    bvid: str,
    results: dict[str, StoredArtifact],
    created_at: str | None = None,
) -> None:
    """Record a completed transcription run to the history DB."""
    try:
        db = _get_history_db()
    except Exception as exc:
        logger.warning("无法初始化历史数据库，跳过记录: %s", exc)
        return

    try:
        # 从 results 中提取元信息
        metadata = results.get("_metadata")
        author = metadata.author if metadata else ""
        pubdate = metadata.pubdate if metadata else ""

        record_pipeline_run(
            db=db,
            bvid=bvid,
            results=results,
            author=author,
            pubdate=pubdate,
            created_at=created_at,
        )
    except Exception as exc:
        logger.warning("记录历史转录失败: %s", exc)


def _run_job(
    job_id: str,
    *,
    url: str,
    skip_summary: bool,
    summary_preset: str | None,
    summary_profile: str | None,
) -> None:
    try:
        config = _get_app_config()
        storage_backend = _get_storage_backend()
    except FileNotFoundError as exc:
        error_message = str(exc) or "配置文件或总结 preset 配置文件不存在"
        _update_job(
            job_id,
            status="failed",
            stage="failed",
            stage_label="处理失败",
            progress=0,
            error=error_message,
        )
        _append_job_log(
            job_id,
            f"{datetime.now().strftime(JOB_LOG_DATE_FORMAT)} [ERROR] b2t.pipeline: {_redact_text(error_message)}",
        )
        return
    except Exception as exc:
        error_message = str(exc) or "初始化配置或存储后端失败"
        _update_job(
            job_id,
            status="failed",
            stage="failed",
            stage_label="处理失败",
            progress=0,
            error=error_message,
        )
        _append_job_log(
            job_id,
            f"{datetime.now().strftime(JOB_LOG_DATE_FORMAT)} [ERROR] b2t.pipeline: {_redact_text(error_message)}",
        )
        return

    bvid = extract_bvid(url)
    if bvid is not None:
        try:
            existing_results = storage_backend.find_existing_transcription(bvid)
        except Exception as exc:
            logger.warning("查询历史转录结果失败，将继续正常转录: %s", exc)
            existing_results = None

        if existing_results is not None:
            if skip_summary:
                try:
                    success_fields = _build_success_download_fields(existing_results)
                except ValueError:
                    pass
                else:
                    all_artifacts = _collect_all_artifacts_for_bvid(
                        storage_backend,
                        bvid,
                        existing_results,
                    )
                    notice = f"检测到 {bvid} 已经转录过，已直接返回历史文件。"
                    _update_job(
                        job_id,
                        status="succeeded",
                        stage="completed",
                        stage_label="已命中历史转录结果",
                        progress=100,
                        already_transcribed=True,
                        notice=notice,
                        all_downloads=_build_all_download_items(all_artifacts),
                        error=None,
                        **success_fields,
                    )
                    _append_job_log(
                        job_id,
                        f"{datetime.now().strftime(JOB_LOG_DATE_FORMAT)} [INFO] b2t.pipeline: {_redact_text(notice)}",
                    )
                    _record_history(bvid=bvid, results=existing_results)
                    return
            else:
                _update_job(
                    job_id,
                    status="running",
                    stage="summarizing",
                    stage_label="命中历史转录，正在重新总结",
                    progress=90,
                )
                try:
                    summary_results = _run_summary_only_from_existing(
                        bvid=bvid,
                        storage_backend=storage_backend,
                        config=config,
                        existing_results=existing_results,
                        summary_preset=summary_preset,
                        summary_profile=summary_profile,
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

                combined_results = dict(existing_results)
                combined_results.update(summary_results)
                try:
                    success_fields = _build_success_download_fields(combined_results)
                except ValueError as exc:
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

                all_artifacts = _collect_all_artifacts_for_bvid(
                    storage_backend,
                    bvid,
                    combined_results,
                )
                notice = (
                    f"检测到 {bvid} 已经转录过，已复用历史转录并完成新的总结。"
                )
                _update_job(
                    job_id,
                    status="succeeded",
                    stage="completed",
                    stage_label="处理完成（复用历史转录）",
                    progress=100,
                    already_transcribed=True,
                    notice=notice,
                    all_downloads=_build_all_download_items(all_artifacts),
                    error=None,
                    **success_fields,
                )
                _append_job_log(
                    job_id,
                    f"{datetime.now().strftime(JOB_LOG_DATE_FORMAT)} [INFO] b2t.pipeline: {_redact_text(notice)}",
                )
                _record_history(bvid=bvid, results=combined_results)
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
                summary_profile=summary_profile,
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

        try:
            success_fields = _build_success_download_fields(results)
        except ValueError as exc:
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

        # 提取元信息
        metadata = results.get("_metadata")
        metadata_fields = {}
        if metadata:
            metadata_fields["author"] = metadata.author
            metadata_fields["pubdate"] = metadata.pubdate
        if bvid:
            metadata_fields["bvid"] = bvid

        try:
            all_artifacts = _collect_all_artifacts_for_bvid(
                storage_backend, bvid, results
            )
            all_downloads = _build_all_download_items(all_artifacts)
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

        _update_job(
            job_id,
            status="succeeded",
            stage="completed",
            stage_label="处理完成",
            progress=100,
            already_transcribed=False,
            notice=None,
            all_downloads=all_downloads,
            error=None,
            **success_fields,
            **metadata_fields,
        )
        if bvid is not None:
            _record_history(bvid=bvid, results=results)
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
    summary_profile = (
        payload.summary_profile.strip() if payload.summary_profile else None
    )
    if summary_profile == "":
        summary_profile = None

    job = _create_job(
        skip_summary=payload.skip_summary,
        summary_preset=summary_preset,
        summary_profile=summary_profile,
    )
    Thread(
        target=_run_job,
        kwargs={
            "job_id": str(job["job_id"]),
            "url": payload.url.strip(),
            "skip_summary": payload.skip_summary,
            "summary_preset": summary_preset,
            "summary_profile": summary_profile,
        },
        daemon=True,
    ).start()

    return ProcessStartResponse(job_id=str(job["job_id"]))


@app.get("/api/process/{job_id}", response_model=ProcessStatusResponse)
def process_status(job_id: str) -> ProcessStatusResponse:
    job = _get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在或已过期")

    all_downloads_raw = job.get("all_downloads")
    all_downloads: list[DownloadItemResponse] = []
    if isinstance(all_downloads_raw, list):
        for item in all_downloads_raw:
            if not isinstance(item, dict):
                continue
            url = item.get("url")
            filename = item.get("filename")
            kind = item.get("kind")
            if not (
                isinstance(url, str)
                and isinstance(filename, str)
                and isinstance(kind, str)
            ):
                continue
            all_downloads.append(
                DownloadItemResponse(url=url, filename=filename, kind=kind)
            )

    return ProcessStatusResponse(
        job_id=str(job["job_id"]),
        status=str(job["status"]),
        stage=str(job["stage"]),
        stage_label=str(job["stage_label"]),
        progress=int(job["progress"]),
        download_url=str(job["download_url"]),
        filename=job["filename"] if isinstance(job["filename"], str) else None,
        txt_download_url=job["txt_download_url"]
        if isinstance(job["txt_download_url"], str)
        else None,
        txt_filename=job["txt_filename"]
        if isinstance(job["txt_filename"], str)
        else None,
        summary_download_url=job["summary_download_url"]
        if isinstance(job["summary_download_url"], str)
        else None,
        summary_filename=job["summary_filename"]
        if isinstance(job["summary_filename"], str)
        else None,
        summary_txt_download_url=job["summary_txt_download_url"]
        if isinstance(job["summary_txt_download_url"], str)
        else None,
        summary_txt_filename=job["summary_txt_filename"]
        if isinstance(job["summary_txt_filename"], str)
        else None,
        summary_table_pdf_download_url=job["summary_table_pdf_download_url"]
        if isinstance(job["summary_table_pdf_download_url"], str)
        else None,
        summary_table_pdf_filename=job["summary_table_pdf_filename"]
        if isinstance(job["summary_table_pdf_filename"], str)
        else None,
        summary_preset=job["summary_preset"]
        if isinstance(job["summary_preset"], str)
        else None,
        summary_profile=job["summary_profile"]
        if isinstance(job["summary_profile"], str)
        else None,
        already_transcribed=bool(job.get("already_transcribed")),
        notice=job["notice"] if isinstance(job.get("notice"), str) else None,
        all_downloads=all_downloads,
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
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=503,
            detail=str(exc) or "配置文件或总结 preset 配置文件不存在",
        ) from None

    try:
        selected = resolve_summary_preset_name(
            summarize=config.summarize,
            summary_presets=config.summary_presets,
            override=config.summarize.preset,
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


@app.get("/api/summarize-profiles", response_model=SummaryProfileListResponse)
def summarize_profiles() -> SummaryProfileListResponse:
    try:
        config = _get_app_config()
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=503,
            detail=str(exc) or "配置文件或总结 preset 配置文件不存在",
        ) from None

    try:
        resolve_summarize_model_profile(config.summarize)
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    profiles = [
        SummaryProfileItemResponse(
            name=name,
            model=profile.model,
            endpoint=profile.endpoint,
        )
        for name, profile in config.summarize.profiles.items()
    ]
    return SummaryProfileListResponse(
        default_profile=config.summarize.profile,
        selected_profile=config.summarize.profile,
        profiles=profiles,
    )


def _media_type_for_filename(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix in {".md", ".markdown"}:
        return "text/markdown; charset=utf-8"
    if suffix == ".txt":
        return "text/plain; charset=utf-8"
    if suffix == ".pdf":
        return "application/pdf"
    return "application/octet-stream"


@app.get("/api/download/{download_id}")
def download_markdown(download_id: str) -> StreamingResponse:
    with _download_lock:
        artifact = _download_index.get(download_id)

    if artifact is None:
        raise HTTPException(status_code=404, detail="下载链接不存在或已过期")

    storage_backend = _get_storage_backend()
    stream_cm = storage_backend.open_stream(artifact.storage_key)
    try:
        stream = stream_cm.__enter__()
    except FileNotFoundError:
        raise HTTPException(status_code=410, detail="文件不存在，请重新生成") from None
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"读取存储文件失败: {exc}",
        ) from exc

    def iter_stream():
        try:
            while True:
                chunk = stream.read(1024 * 1024)
                if not chunk:
                    break
                yield chunk
        finally:
            stream_cm.__exit__(None, None, None)

    quoted_filename = quote(artifact.filename)
    return StreamingResponse(
        iter_stream(),
        media_type=_media_type_for_filename(artifact.filename),
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quoted_filename}"
        },
    )


@app.get("/api/history", response_model=HistoryListResponse)
def list_history(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    search: str = Query(default=""),
) -> HistoryListResponse:
    try:
        db = _get_history_db()
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"历史数据库初始化失败: {exc}",
        ) from exc

    result = db.list_runs(page=page, page_size=page_size, search=search)
    return HistoryListResponse(
        items=[
            HistoryItemResponse(
                run_id=item.run_id,
                bvid=item.bvid,
                title=item.title,
                author=item.author,
                pubdate=item.pubdate,
                created_at=item.created_at,
                has_summary=item.has_summary,
                file_count=item.file_count,
            )
            for item in result.items
        ],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
        has_more=result.has_more,
    )


@app.get("/api/history/{run_id}", response_model=HistoryDetailResponse)
def history_detail(run_id: str) -> HistoryDetailResponse:
    try:
        db = _get_history_db()
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"历史数据库初始化失败: {exc}",
        ) from exc

    detail = db.get_run_detail(run_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="转录记录不存在")

    storage_backend = _get_storage_backend()
    artifacts: list[HistoryDetailArtifactResponse] = []
    for a in detail.artifacts:
        stored = StoredArtifact(
            filename=a.filename,
            storage_key=a.storage_key,
            backend=a.backend,
        )
        download_id = _store_download(stored)
        artifacts.append(
            HistoryDetailArtifactResponse(
                kind=a.kind,
                filename=a.filename,
                download_url=f"/api/download/{download_id}",
            )
        )

    return HistoryDetailResponse(
        run_id=detail.run_id,
        bvid=detail.bvid,
        title=detail.title,
        author=detail.author,
        pubdate=detail.pubdate,
        created_at=detail.created_at,
        has_summary=detail.has_summary,
        artifacts=artifacts,
    )


@app.delete("/api/history/{run_id}")
def delete_history(run_id: str) -> dict[str, str]:
    """Delete a history record and its associated files."""
    try:
        db = _get_history_db()
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"历史数据库初始化失败: {exc}",
        ) from exc

    # Check if record exists
    detail = db.get_run_detail(run_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="转录记录不存在")

    # Delete from database and get artifacts
    artifacts = db.delete_run(run_id)

    # Delete files
    storage_backend = _get_storage_backend()
    deleted_count = 0
    failed_files: list[str] = []

    for artifact in artifacts:
        try:
            storage_backend.delete_file(artifact.storage_key)
            deleted_count += 1
        except Exception as exc:
            logger.warning(
                "删除文件 %s 失败: %s",
                artifact.filename,
                exc,
            )
            failed_files.append(artifact.filename)

    if failed_files:
        logger.warning(
            "删除记录 %s 时，部分文件删除失败: %s",
            run_id,
            ", ".join(failed_files),
        )

    return {
        "message": f"已删除记录，成功删除 {deleted_count} 个文件"
        + (f"，{len(failed_files)} 个文件删除失败" if failed_files else "")
    }


@app.post("/api/convert", response_model=ConvertResponse)
def convert_artifact(payload: ConvertRequest) -> ConvertResponse:
    """
    在线转换文件格式。

    支持的转换：
    - Markdown -> txt, pdf, png, html
    """
    with _download_lock:
        artifact = _download_index.get(payload.download_id)

    if artifact is None:
        raise HTTPException(status_code=404, detail="下载链接不存在或已过期")

    # 验证目标格式
    try:
        target_format = ConversionFormat(payload.target_format.lower())
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的目标格式: {payload.target_format}",
        ) from None

    # 检查源文件格式
    source_suffix = Path(artifact.filename).suffix.lower().lstrip(".")
    if source_suffix not in ("md", "markdown"):
        raise HTTPException(
            status_code=400,
            detail=f"不支持转换此文件类型: {source_suffix}",
        )

    storage_backend = _get_storage_backend()

    # 下载源文件到临时目录
    with tempfile.TemporaryDirectory(prefix="b2t-convert-") as temp_dir:
        temp_dir_path = Path(temp_dir)
        source_path = temp_dir_path / artifact.filename

        try:
            with storage_backend.open_stream(artifact.storage_key) as stream:
                with source_path.open("wb") as output:
                    while True:
                        chunk = stream.read(1024 * 1024)
                        if not chunk:
                            break
                        output.write(chunk)
        except FileNotFoundError:
            raise HTTPException(
                status_code=410,
                detail="源文件不存在，请重新生成",
            ) from None
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail=f"读取源文件失败: {exc}",
            ) from exc

        # 执行转换
        try:
            source_kind = classify_artifact_filename(artifact.filename) or ""
            png_is_table = (
                target_format == ConversionFormat.PNG
                and source_kind == "summary_table_md"
            )
            output_path = convert_file(
                source_path,
                target_format,
                is_table=png_is_table,
            )
        except RuntimeError as exc:
            raise HTTPException(
                status_code=500,
                detail=str(exc),
            ) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail=f"转换失败: {exc}",
            ) from exc

        # 存储转换后的文件
        converted_filename = output_path.name
        try:
            converted_artifact = storage_backend.store_file(
                output_path,
                object_key=f"converted/{uuid4().hex}/{converted_filename}",
            )
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail=f"保存转换结果失败: {exc}",
            ) from exc

    # 注册下载
    download_id = _store_download(converted_artifact)

    return ConvertResponse(
        download_url=f"/api/download/{download_id}",
        filename=converted_filename,
    )
