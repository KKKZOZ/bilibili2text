"""Process endpoints: submit a video URL and poll job status."""

from threading import Thread

from fastapi import APIRouter, HTTPException

from backend.jobs import _create_job, _get_job
from backend.runner import _run_job
from backend.schemas import (
    DownloadItemResponse,
    ProcessRequest,
    ProcessStartResponse,
    ProcessStatusResponse,
)

router = APIRouter()


@router.post("/api/process", response_model=ProcessStartResponse)
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


@router.get("/api/process/{job_id}", response_model=ProcessStatusResponse)
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
