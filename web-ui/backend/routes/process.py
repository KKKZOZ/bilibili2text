"""Process endpoints: submit a video URL / upload audio and poll job status."""

import shutil
import tempfile
from pathlib import Path
import re

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from backend.jobs import _create_job, _get_job, _list_active_jobs
from backend.job_store import job_repository
from backend.runner import _run_job
from backend.schemas import (
    ActiveJobItem,
    ActiveJobsResponse,
    DownloadItemResponse,
    ProcessRequest,
    ProcessStartResponse,
    ProcessStatusResponse,
)
from backend.settings import get_runtime_app_config, is_upload_enabled
from backend.task_queue import submit_job
from b2t.summarize.llm import validate_summary_prompt_template

router = APIRouter()
_UPLOAD_BVID_NAME_PATTERN = re.compile(r"^(BV[0-9A-Za-z]{10})_(.+)$", re.IGNORECASE)
_ALLOWED_AUDIO_SUFFIXES = {
    ".aac",
    ".flac",
    ".m4a",
    ".mp3",
    ".ogg",
    ".opus",
    ".wav",
    ".webm",
}


def _clean_optional_text(value: str | None) -> str | None:
    cleaned = value.strip() if value else ""
    return cleaned or None


def _clean_optional_prompt_template(value: str | None) -> str | None:
    cleaned = _clean_optional_text(value)
    if cleaned is None:
        return None
    return validate_summary_prompt_template(cleaned)


def _normalize_bvid(raw: str) -> str:
    return "BV" + raw[2:]


def _extract_bvid_from_upload_filename(filename: str) -> str | None:
    stem = Path(filename).stem
    match = _UPLOAD_BVID_NAME_PATTERN.match(stem)
    if match is None:
        return None
    return _normalize_bvid(match.group(1))


def _validate_upload_filename(filename: str) -> tuple[str, str]:
    safe_name = Path(filename or "").name.strip()
    if not safe_name:
        raise HTTPException(status_code=400, detail="上传文件名不能为空")

    suffix = Path(safe_name).suffix.lower()
    if suffix not in _ALLOWED_AUDIO_SUFFIXES:
        allowed = ", ".join(sorted(_ALLOWED_AUDIO_SUFFIXES))
        raise HTTPException(
            status_code=400,
            detail=f"不支持的音频格式: {suffix or '(无扩展名)'}，仅支持 {allowed}",
        )

    bvid = _extract_bvid_from_upload_filename(safe_name)
    if bvid is None:
        raise HTTPException(
            status_code=400,
            detail=(
                "上传文件名必须符合规范：`BV号_视频标题.xxx`，"
                "例如 `BV1R9i4BoE7H_视频标题.m4a`"
            ),
        )
    return safe_name, bvid


def _ensure_runtime_ready(
    api_key: str | None = None,
    deepseek_api_key: str | None = None,
    summary_profile: str | None = None,
) -> None:
    try:
        config = get_runtime_app_config(
            require_public_api_key=True,
            api_key=api_key,
            deepseek_api_key=deepseek_api_key,
        )
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=503,
            detail=str(exc) or "配置文件或总结 preset 配置文件不存在",
        ) from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"初始化配置失败: {exc}",
        ) from exc

    # Validate that the selected profile has a usable API key.
    profile_name = summary_profile or config.summarize.profile
    profile = config.summarize.profiles.get(profile_name)
    if profile is not None and not profile.api_key.strip():
        provider_label = (
            "DeepSeek"
            if profile.provider.strip().lower() == "deepseek"
            else profile.provider
        )
        raise HTTPException(
            status_code=400,
            detail=(
                f"模型 {profile_name}（{provider_label}）需要 API Key，"
                "但你未提供。请在「API Key」页面配置对应的 Key 后再试。"
            ),
        )


@router.post("/api/process", response_model=ProcessStartResponse)
def process_video(payload: ProcessRequest) -> ProcessStartResponse:
    if not payload.url.strip():
        raise HTTPException(status_code=400, detail="URL 不能为空")

    summary_preset = _clean_optional_text(payload.summary_preset)
    summary_profile = _clean_optional_text(payload.summary_profile)
    summary_prompt_template = _clean_optional_prompt_template(
        payload.summary_prompt_template
    )

    _ensure_runtime_ready(
        api_key=_clean_optional_text(payload.api_key),
        deepseek_api_key=_clean_optional_text(payload.deepseek_api_key),
        summary_profile=summary_profile,
    )

    job = _create_job(
        skip_summary=payload.skip_summary,
        summary_preset=summary_preset,
        summary_profile=summary_profile,
        summary_prompt_template=summary_prompt_template,
        auto_generate_fancy_html=payload.auto_generate_fancy_html,
    )
    submit_job(
        _run_job,
        job_id=str(job["job_id"]),
        url=payload.url.strip(),
        skip_summary=payload.skip_summary,
        summary_preset=summary_preset,
        summary_profile=summary_profile,
        summary_prompt_template=summary_prompt_template,
        auto_generate_fancy_html=payload.auto_generate_fancy_html,
        api_key=_clean_optional_text(payload.api_key),
        deepseek_api_key=_clean_optional_text(payload.deepseek_api_key),
    )

    return ProcessStartResponse(job_id=str(job["job_id"]))


@router.post("/api/process/upload", response_model=ProcessStartResponse)
def process_uploaded_audio(
    file: UploadFile = File(..., description="待转录的音频文件"),
    skip_summary: bool = Form(default=False),
    summary_preset: str | None = Form(default=None),
    summary_profile: str | None = Form(default=None),
    summary_prompt_template: str | None = Form(default=None),
    auto_generate_fancy_html: bool = Form(default=False),
    api_key: str | None = Form(default=None),
    deepseek_api_key: str | None = Form(default=None),
) -> ProcessStartResponse:
    if not is_upload_enabled():
        raise HTTPException(
            status_code=403,
            detail="open-public 模式不允许直接上传音频文件，请改为输入视频 URL 或 BV 号",
        )
    _ensure_runtime_ready(
        api_key=_clean_optional_text(api_key),
        deepseek_api_key=_clean_optional_text(deepseek_api_key),
        summary_profile=_clean_optional_text(summary_profile),
    )

    safe_filename, bvid = _validate_upload_filename(file.filename or "")
    cleaned_summary_preset = _clean_optional_text(summary_preset)
    cleaned_summary_profile = _clean_optional_text(summary_profile)
    cleaned_summary_prompt_template = _clean_optional_prompt_template(
        summary_prompt_template
    )

    temp_dir = Path(tempfile.mkdtemp(prefix="b2t-upload-"))
    upload_path = temp_dir / safe_filename
    try:
        with upload_path.open("wb") as output:
            while True:
                chunk = file.file.read(1024 * 1024)
                if not chunk:
                    break
                output.write(chunk)
    except Exception as exc:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=f"保存上传文件失败: {exc}") from exc
    finally:
        file.file.close()

    if upload_path.stat().st_size <= 0:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise HTTPException(status_code=400, detail="上传文件为空")

    job = _create_job(
        skip_summary=skip_summary,
        summary_preset=cleaned_summary_preset,
        summary_profile=cleaned_summary_profile,
        summary_prompt_template=cleaned_summary_prompt_template,
        auto_generate_fancy_html=auto_generate_fancy_html,
    )
    submit_job(
        _run_job,
        job_id=str(job["job_id"]),
        url=None,
        input_audio_path=str(upload_path),
        input_bvid=bvid,
        skip_summary=skip_summary,
        summary_preset=cleaned_summary_preset,
        summary_profile=cleaned_summary_profile,
        summary_prompt_template=cleaned_summary_prompt_template,
        auto_generate_fancy_html=auto_generate_fancy_html,
        api_key=_clean_optional_text(api_key),
        deepseek_api_key=_clean_optional_text(deepseek_api_key),
    )

    return ProcessStartResponse(job_id=str(job["job_id"]))


@router.get("/api/jobs/active", response_model=ActiveJobsResponse)
def list_active_jobs() -> ActiveJobsResponse:
    jobs = _list_active_jobs()
    return ActiveJobsResponse(jobs=[ActiveJobItem(**j) for j in jobs])


@router.post("/api/process/{job_id}/cancel")
def cancel_job(job_id: str) -> dict:
    cancelled, status = job_repository.cancel(job_id)
    if status is None:
        raise HTTPException(status_code=404, detail="任务不存在或已过期")
    if not cancelled:
        raise HTTPException(
            status_code=400,
            detail=f"只能取消进行中的任务（当前状态：{status}）",
        )
    return {"ok": True, "job_id": job_id}


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
        skip_summary=bool(job.get("skip_summary")),
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
        summary_prompt_template=job["summary_prompt_template"]
        if isinstance(job.get("summary_prompt_template"), str)
        else None,
        auto_generate_fancy_html=bool(job.get("auto_generate_fancy_html")),
        fancy_html_status=str(job.get("fancy_html_status") or "idle"),
        fancy_html_error=job["fancy_html_error"]
        if isinstance(job.get("fancy_html_error"), str)
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
        author=job["author"] if isinstance(job.get("author"), str) else None,
        pubdate=job["pubdate"] if isinstance(job.get("pubdate"), str) else None,
        bvid=job["bvid"] if isinstance(job.get("bvid"), str) else None,
        title=job["title"] if isinstance(job.get("title"), str) else None,
    )
