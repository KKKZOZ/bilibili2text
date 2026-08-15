"""Typed in-memory job state and lifecycle operations."""

from __future__ import annotations

import time
from collections import OrderedDict
from collections.abc import Callable
from concurrent.futures import CancelledError, Future
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from threading import Lock, RLock
from uuid import uuid4

from b2t.cancellation import CancellationToken
from backend.event_stream import event_broker, job_channel
from backend.settings import JOB_LOG_LIMIT, STAGE_KEYS, utc_iso

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
    | dict[str, object]
)


@dataclass(slots=True)
class JobState:
    job_id: str
    status: str
    stage: str
    stage_label: str
    progress: int
    download_url: str
    filename: str | None
    txt_download_url: str | None
    txt_filename: str | None
    summary_download_url: str | None
    summary_filename: str | None
    summary_txt_download_url: str | None
    summary_txt_filename: str | None
    summary_table_pdf_download_url: str | None
    summary_table_pdf_filename: str | None
    already_transcribed: bool
    notice: str | None
    all_downloads: list[dict[str, str]]
    error: str | None
    created_at: str
    updated_at: str
    skip_summary: bool
    summary_preset: str | None
    summary_profile: str | None
    summary_prompt_template: str | None
    auto_generate_fancy_html: bool
    fancy_html_status: str
    fancy_html_error: str | None
    used_bilibili_subtitle: bool
    logs: list[str] = field(default_factory=list)
    stage_started_monotonic: float = field(default_factory=time.monotonic)
    stage_durations_seconds: dict[str, int] = field(
        default_factory=lambda: {key: 0 for key in STAGE_KEYS}
    )
    stage_seen: dict[str, bool] = field(
        default_factory=lambda: {key: key == "queued" for key in STAGE_KEYS}
    )
    author: str | None = None
    pubdate: str | None = None
    bvid: str | None = None
    title: str | None = None
    duration_seconds: int = 0
    tname: str | None = None
    parent_tname: str | None = None
    comment_status: str = "disabled"
    comment_limit: int = 200
    comment_count: int = 0
    comment_reply_count: int = 0
    history_run_id: str | None = None
    is_ephemeral_upload: bool = False
    expires_at: str | None = None
    ephemeral_artifacts: list[dict[str, str]] = field(default_factory=list)

    @classmethod
    def create(
        cls,
        *,
        skip_summary: bool,
        summary_preset: str | None,
        summary_profile: str | None,
        summary_prompt_template: str | None,
        auto_generate_fancy_html: bool,
    ) -> JobState:
        now = utc_iso()
        return cls(
            job_id=uuid4().hex,
            status="queued",
            stage="queued",
            stage_label="任务已创建，等待开始",
            progress=0,
            download_url="",
            filename=None,
            txt_download_url=None,
            txt_filename=None,
            summary_download_url=None,
            summary_filename=None,
            summary_txt_download_url=None,
            summary_txt_filename=None,
            summary_table_pdf_download_url=None,
            summary_table_pdf_filename=None,
            already_transcribed=False,
            notice=None,
            all_downloads=[],
            error=None,
            created_at=now,
            updated_at=now,
            skip_summary=skip_summary,
            summary_preset=summary_preset,
            summary_profile=summary_profile,
            summary_prompt_template=summary_prompt_template,
            auto_generate_fancy_html=auto_generate_fancy_html,
            fancy_html_status=(
                "pending" if auto_generate_fancy_html and not skip_summary else "idle"
            ),
            fancy_html_error=None,
            used_bilibili_subtitle=False,
        )

    def to_payload(self) -> dict[str, JobValue]:
        return asdict(self)


@dataclass(slots=True)
class JobPatch:
    status: str | None = None
    stage: str | None = None
    stage_label: str | None = None
    progress: int | None = None
    error: str | None = None
    download_url: str | None = None
    filename: str | None = None
    txt_download_url: str | None = None
    txt_filename: str | None = None
    summary_download_url: str | None = None
    summary_filename: str | None = None
    summary_txt_download_url: str | None = None
    summary_txt_filename: str | None = None
    summary_table_pdf_download_url: str | None = None
    summary_table_pdf_filename: str | None = None
    auto_generate_fancy_html: bool | None = None
    fancy_html_status: str | None = None
    fancy_html_error: str | None = None
    used_bilibili_subtitle: bool | None = None
    already_transcribed: bool | None = None
    notice: str | None = None
    all_downloads: list[dict[str, str]] | None = None
    author: str | None = None
    pubdate: str | None = None
    bvid: str | None = None
    title: str | None = None
    duration_seconds: int | None = None
    tname: str | None = None
    parent_tname: str | None = None
    comment_status: str | None = None
    comment_limit: int | None = None
    comment_count: int | None = None
    comment_reply_count: int | None = None
    history_run_id: str | None = None
    is_ephemeral_upload: bool | None = None
    expires_at: str | None = None
    ephemeral_artifacts: list[dict[str, str]] | None = None


class JobCapacityError(RuntimeError):
    """Raised when retained active jobs leave no room for another record."""


def _format_elapsed(seconds: int) -> str:
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


class JobRepository:
    def __init__(
        self,
        *,
        limit: int = 200,
        on_change: Callable[[str], None] | None = None,
    ) -> None:
        self._jobs: OrderedDict[str, JobState] = OrderedDict()
        self._limit = limit
        self._lock = Lock()
        self._on_change = on_change

    def _notify_change(self, job_id: str) -> None:
        if self._on_change is not None:
            self._on_change(job_id)

    def create(
        self,
        *,
        skip_summary: bool,
        summary_preset: str | None,
        summary_profile: str | None,
        summary_prompt_template: str | None = None,
        auto_generate_fancy_html: bool,
    ) -> dict[str, JobValue]:
        job = JobState.create(
            skip_summary=skip_summary,
            summary_preset=summary_preset,
            summary_profile=summary_profile,
            summary_prompt_template=summary_prompt_template,
            auto_generate_fancy_html=auto_generate_fancy_html,
        )
        with self._lock:
            self._evict_terminal_jobs_locked()
            if len(self._jobs) >= self._limit:
                raise JobCapacityError("任务记录容量已满，当前任务仍在处理中")
            self._jobs[job.job_id] = job
            payload = job.to_payload()
        self._notify_change(job.job_id)
        return payload

    def _evict_terminal_jobs_locked(self) -> None:
        while len(self._jobs) >= self._limit:
            terminal_job_id = next(
                (
                    job_id
                    for job_id, job in self._jobs.items()
                    if job.status in {"succeeded", "failed", "cancelled"}
                ),
                None,
            )
            if terminal_job_id is None:
                return
            del self._jobs[terminal_job_id]

    def patch(self, job_id: str, patch: JobPatch) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            if job.status == "cancelled":
                return

            now_mono = time.monotonic()
            current_stage = job.stage
            next_stage = patch.stage if patch.stage is not None else current_stage
            if (
                patch.stage is not None
                and current_stage in STAGE_KEYS
                and next_stage != current_stage
            ):
                elapsed = max(0, int(now_mono - job.stage_started_monotonic))
                job.stage_durations_seconds[current_stage] = (
                    job.stage_durations_seconds.get(current_stage, 0) + elapsed
                )
                job.stage_started_monotonic = now_mono

            if patch.stage is not None and patch.stage in STAGE_KEYS:
                job.stage_seen[patch.stage] = True

            for field_name, value in asdict(patch).items():
                if value is None:
                    continue
                if field_name == "progress":
                    value = max(0, min(100, int(value)))
                setattr(job, field_name, value)

            job.updated_at = utc_iso()
        self._notify_change(job_id)

    def cancel(self, job_id: str) -> tuple[bool, str | None]:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return False, None
            if job.status not in ("queued", "running"):
                return False, job.status
            job.status = "cancelled"
            job.stage = "cancelled"
            job.stage_label = "任务已取消"
            job.error = "任务已被用户取消"
            job.updated_at = utc_iso()
            status = job.status
        self._notify_change(job_id)
        return True, status

    def append_log(self, job_id: str, line: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.status == "cancelled":
                return
            job.logs.append(line)
            if len(job.logs) > JOB_LOG_LIMIT:
                del job.logs[:-JOB_LOG_LIMIT]
            job.updated_at = utc_iso()
        self._notify_change(job_id)

    def list_active(self) -> list[dict[str, JobValue]]:
        with self._lock:
            return [
                {
                    "job_id": job.job_id,
                    "status": job.status,
                    "stage": job.stage,
                    "stage_label": job.stage_label,
                    "progress": job.progress,
                    "bvid": job.bvid,
                    "title": job.title,
                    "author": job.author,
                    "created_at": job.created_at,
                    "updated_at": job.updated_at,
                }
                for job in self._jobs.values()
                if job.status in ("queued", "running")
            ]

    def get(self, job_id: str) -> dict[str, JobValue] | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            payload = job.to_payload()
            payload["stage_durations"] = self._build_stage_duration_labels(job)
            return payload

    def mark_expired(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.status == "cancelled":
                return
            job.status = "failed"
            job.stage = "failed"
            job.stage_label = "临时文件已过期"
            job.error = "临时上传转录结果已过期，请重新上传。"
            job.all_downloads = []
            job.download_url = ""
            job.filename = None
            job.txt_download_url = None
            job.txt_filename = None
            job.summary_download_url = None
            job.summary_filename = None
            job.summary_txt_download_url = None
            job.summary_txt_filename = None
            job.summary_table_pdf_download_url = None
            job.summary_table_pdf_filename = None
            job.ephemeral_artifacts = []
            job.updated_at = utc_iso()
        self._notify_change(job_id)

    def list_expired_ephemeral_uploads(
        self, *, now: datetime | None = None
    ) -> list[dict[str, object]]:
        cutoff = now or datetime.now(tz=UTC)
        expired: list[dict[str, object]] = []
        with self._lock:
            for job in self._jobs.values():
                if not job.is_ephemeral_upload or not job.expires_at:
                    continue
                if job.status not in {"succeeded", "failed", "cancelled"}:
                    continue
                try:
                    expires_at = datetime.fromisoformat(job.expires_at)
                except ValueError:
                    continue
                if expires_at.tzinfo is None:
                    expires_at = expires_at.replace(tzinfo=UTC)
                if expires_at > cutoff:
                    continue
                expired.append(
                    {
                        "job_id": job.job_id,
                        "artifacts": list(job.ephemeral_artifacts),
                    }
                )
        return expired

    def _snapshot_stage_durations(self, job: JobState) -> dict[str, int]:
        snapshot = {
            key: max(0, job.stage_durations_seconds.get(key, 0)) for key in STAGE_KEYS
        }
        if job.stage in snapshot and job.status in {"queued", "running"}:
            snapshot[job.stage] += max(
                0,
                int(time.monotonic() - job.stage_started_monotonic),
            )
        return snapshot

    def _build_stage_duration_labels(self, job: JobState) -> dict[str, str]:
        durations = self._snapshot_stage_durations(job)
        labels: dict[str, str] = {}
        for key in STAGE_KEYS:
            if job.skip_summary and key == "summarizing":
                labels[key] = "跳过"
                continue
            if job.stage_seen.get(key, False) or key == job.stage or durations[key] > 0:
                labels[key] = _format_elapsed(durations[key])
            else:
                labels[key] = "--"
        return labels


class JobManager(JobRepository):
    """Own job state, submitted futures, and cooperative cancellation tokens."""

    def __init__(
        self,
        *,
        limit: int = 200,
        on_change: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(limit=limit, on_change=on_change)
        self._futures: dict[str, Future] = {}
        self._tokens: dict[str, CancellationToken] = {}
        self._lifecycle_lock = RLock()

    def create(self, **kwargs) -> dict[str, JobValue]:
        job = super().create(**kwargs)
        job_id = str(job["job_id"])
        with self._lifecycle_lock:
            self._tokens[job_id] = CancellationToken()
            with self._lock:
                retained_job_ids = set(self._jobs)
            self._tokens = {
                retained_id: token
                for retained_id, token in self._tokens.items()
                if retained_id in retained_job_ids
            }
            self._futures = {
                retained_id: future
                for retained_id, future in self._futures.items()
                if retained_id in retained_job_ids
            }
        return job

    def cancellation_token(self, job_id: str) -> CancellationToken | None:
        with self._lifecycle_lock:
            return self._tokens.get(job_id)

    def submit(
        self,
        job_id: str,
        fn: Callable[..., object],
        /,
        *args: object,
        submitter: Callable[..., Future] | None = None,
        **kwargs: object,
    ) -> Future | None:
        """Submit a job and atomically associate its future with its record.

        A rejection is represented by a terminal failed job so clients never
        poll a permanently queued record for work that was not accepted.
        """
        if submitter is None:
            from backend.task_queue import submit_job

            submitter = submit_job
        with self._lifecycle_lock:
            token = self._tokens.get(job_id)
        if token is None:
            # Preserve legacy callers that submit work for externally managed jobs.
            return submitter(fn, *args, **kwargs)
        kwargs.setdefault("cancellation_token", token)
        try:
            future = submitter(fn, *args, **kwargs)
        except Exception as exc:
            self.patch(
                job_id,
                JobPatch(
                    status="failed",
                    stage="failed",
                    stage_label="任务未能提交",
                    error=f"后台任务提交失败: {exc}",
                ),
            )
            self.append_log(job_id, f"[ERROR] 后台任务提交失败: {exc}")
            return None

        # Test and legacy submitters may deliberately return no Future.
        if future is None:
            return None

        with self._lifecycle_lock:
            self._futures[job_id] = future
            if token.is_cancelled():
                future.cancel()
        future.add_done_callback(
            lambda completed_future: self._observe_future(job_id, completed_future)
        )
        return future

    def cancel(self, job_id: str) -> tuple[bool, str | None]:
        with self._lifecycle_lock:
            token = self._tokens.get(job_id)
            future = self._futures.get(job_id)
        if token is None:
            cancelled, status = super().cancel(job_id)
        else:
            cancelled, status = token.cancel_if(
                lambda: JobRepository.cancel(self, job_id)
            )
        if cancelled and future is not None:
            future.cancel()
        return cancelled, status

    def _observe_future(self, job_id: str, future: Future) -> None:
        with self._lifecycle_lock:
            if self._futures.get(job_id) is future:
                del self._futures[job_id]
            token = self._tokens.get(job_id)
        if future.cancelled():
            return
        try:
            exception = future.exception()
        except CancelledError:
            return
        if exception is None or (token is not None and token.is_cancelled()):
            return
        self.patch(
            job_id,
            JobPatch(
                status="failed",
                stage="failed",
                stage_label="处理失败",
                error=f"后台任务异常: {exception}",
            ),
        )
        self.append_log(job_id, f"[ERROR] 后台任务异常: {exception}")


job_manager = JobManager(
    on_change=lambda job_id: event_broker.publish(job_channel(job_id))
)
# Kept for callers that still import the original repository name.
job_repository = job_manager
