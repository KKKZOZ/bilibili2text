"""Typed in-memory job state and lifecycle operations."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import asdict, dataclass, field
import time
from threading import Lock
from uuid import uuid4

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

    @classmethod
    def create(
        cls,
        *,
        skip_summary: bool,
        summary_preset: str | None,
        summary_profile: str | None,
        summary_prompt_template: str | None,
        auto_generate_fancy_html: bool,
    ) -> "JobState":
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
    already_transcribed: bool | None = None
    notice: str | None = None
    all_downloads: list[dict[str, str]] | None = None
    author: str | None = None
    pubdate: str | None = None
    bvid: str | None = None
    title: str | None = None


def _format_elapsed(seconds: int) -> str:
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


class JobRepository:
    def __init__(self, *, limit: int = 200) -> None:
        self._jobs: OrderedDict[str, JobState] = OrderedDict()
        self._limit = limit
        self._lock = Lock()

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
            self._jobs[job.job_id] = job
            while len(self._jobs) > self._limit:
                self._jobs.popitem(last=False)
        return job.to_payload()

    def patch(self, job_id: str, patch: JobPatch) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
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

            if job.status == "cancelled":
                return

            for field_name, value in asdict(patch).items():
                if value is None:
                    continue
                if field_name == "progress":
                    value = max(0, min(100, int(value)))
                setattr(job, field_name, value)

            job.updated_at = utc_iso()

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
            return True, job.status

    def append_log(self, job_id: str, line: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.status == "cancelled":
                return
            job.logs.append(line)
            if len(job.logs) > JOB_LOG_LIMIT:
                del job.logs[:-JOB_LOG_LIMIT]
            job.updated_at = utc_iso()

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

    @property
    def legacy_jobs(self) -> OrderedDict[str, JobState]:
        return self._jobs

    @property
    def legacy_lock(self) -> Lock:
        return self._lock


job_repository = JobRepository()
