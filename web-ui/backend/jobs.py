"""Job lifecycle management: create, update, query, and stage duration helpers."""

import time
from uuid import uuid4

from backend.state import (
    JOB_LOG_LIMIT,
    STAGE_KEYS,
    JobValue,
    _job_index,
    _job_lock,
    _job_limit,
    _utc_iso,
)


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
