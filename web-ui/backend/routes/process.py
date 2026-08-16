"""Process endpoints: submit a video URL / upload audio and poll job status."""

import json
import re
import shutil
import subprocess
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse

from backend.event_stream import event_broker, job_channel
from backend.job_store import JobCapacityError, job_manager
from backend.jobs import _create_job, _get_job, _list_active_jobs
from backend.runner import _run_job
from backend.schemas import (
    ActiveJobItem,
    ActiveJobsResponse,
    JobSnapshotsResponse,
    ProcessRequest,
    ProcessStartResponse,
    ProcessStatusResponse,
    SummarySelectionRequest,
)
from backend.settings import (
    get_runtime_app_config,
    is_open_public_mode,
    is_upload_enabled,
)
from backend.task_queue import submit_job

router = APIRouter()
_SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
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
_ALLOWED_VIDEO_SUFFIXES = {
    ".avi",
    ".m4v",
    ".mkv",
    ".mov",
    ".mp4",
    ".webm",
}


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


def _validate_open_public_upload_filename(
    filename: str, content_type: str | None = None
) -> tuple[str, str]:
    safe_name = Path(filename or "").name.strip()
    if not safe_name:
        raise HTTPException(status_code=400, detail="上传文件名不能为空")

    suffix = Path(safe_name).suffix.lower()
    if suffix in _ALLOWED_VIDEO_SUFFIXES:
        if (content_type or "").strip().lower().startswith("audio/"):
            return safe_name, "audio"
        return safe_name, "video"
    if suffix in _ALLOWED_AUDIO_SUFFIXES:
        return safe_name, "audio"

    allowed = ", ".join(sorted(_ALLOWED_AUDIO_SUFFIXES | _ALLOWED_VIDEO_SUFFIXES))
    raise HTTPException(
        status_code=400,
        detail=f"不支持的上传格式: {suffix or '(无扩展名)'}，仅支持 {allowed}",
    )


def _convert_video_upload_to_audio(video_path: Path) -> Path:
    audio_path = video_path.with_suffix(".wav")
    try:
        subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-y",
                "-i",
                str(video_path),
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-c:a",
                "pcm_s16le",
                str(audio_path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=500,
            detail="服务器未安装 ffmpeg，无法处理视频上传",
        ) from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or str(exc)).strip()
        raise HTTPException(
            status_code=400,
            detail=f"视频音频提取失败: {detail}",
        ) from exc

    if not audio_path.exists() or audio_path.stat().st_size <= 0:
        raise HTTPException(status_code=400, detail="视频中未提取到有效音频")
    return audio_path


def _ensure_runtime_ready(
    api_key: str | None = None,
    deepseek_api_key: str | None = None,
    custom_llm_base_url: str | None = None,
    custom_llm_api_key: str | None = None,
    custom_llm_model: str | None = None,
    summary_profile: str | None = None,
) -> None:
    try:
        config = get_runtime_app_config(
            require_public_api_key=True,
            api_key=api_key,
            deepseek_api_key=deepseek_api_key,
            custom_llm_base_url=custom_llm_base_url,
            custom_llm_api_key=custom_llm_api_key,
            custom_llm_model=custom_llm_model,
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

    summary_preset = payload.summary_preset
    summary_profile = payload.summary_profile
    summary_prompt_template = payload.summary_prompt_template

    _ensure_runtime_ready(
        **payload.runtime_config_kwargs(),
        summary_profile=summary_profile,
    )

    try:
        job = _create_job(
            skip_summary=payload.skip_summary,
            summary_preset=summary_preset,
            summary_profile=summary_profile,
            summary_prompt_template=summary_prompt_template,
            auto_generate_fancy_html=payload.auto_generate_fancy_html,
        )
    except JobCapacityError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from None
    job_manager.submit(
        str(job["job_id"]),
        _run_job,
        submitter=submit_job,
        job_id=str(job["job_id"]),
        url=payload.url.strip(),
        skip_summary=payload.skip_summary,
        summary_preset=summary_preset,
        summary_profile=summary_profile,
        summary_prompt_template=summary_prompt_template,
        auto_generate_fancy_html=payload.auto_generate_fancy_html,
        prefer_bilibili_subtitle=payload.prefer_bilibili_subtitle,
        include_comments=payload.include_comments,
        comment_limit=payload.comment_limit,
        **payload.runtime_config_kwargs(),
    )

    return ProcessStartResponse(job_id=str(job["job_id"]))


@router.post("/api/process/upload", response_model=ProcessStartResponse)
def process_uploaded_audio(
    file: UploadFile = File(..., description="待转录的音频文件"),  # noqa: B008
    skip_summary: bool = Form(default=False),
    summary_preset: str | None = Form(default=None),
    summary_profile: str | None = Form(default=None),
    summary_prompt_template: str | None = Form(default=None),
    auto_generate_fancy_html: bool = Form(default=False),
    api_key: str | None = Form(default=None),
    deepseek_api_key: str | None = Form(default=None),
    custom_llm_base_url: str | None = Form(default=None),
    custom_llm_api_key: str | None = Form(default=None),
    custom_llm_model: str | None = Form(default=None),
) -> ProcessStartResponse:
    if not is_upload_enabled():
        raise HTTPException(
            status_code=403,
            detail="当前模式不允许直接上传文件，请改为输入视频 URL 或 BV 号",
        )
    try:
        options = SummarySelectionRequest(
            summary_preset=summary_preset,
            summary_profile=summary_profile,
            summary_prompt_template=summary_prompt_template,
            api_key=api_key,
            deepseek_api_key=deepseek_api_key,
            custom_llm_base_url=custom_llm_base_url,
            custom_llm_api_key=custom_llm_api_key,
            custom_llm_model=custom_llm_model,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _ensure_runtime_ready(
        **options.runtime_config_kwargs(),
        summary_profile=options.summary_profile,
    )

    open_public = is_open_public_mode()
    if open_public:
        safe_filename, upload_kind = _validate_open_public_upload_filename(
            file.filename or "", getattr(file, "content_type", None)
        )
        bvid = None
    else:
        safe_filename, bvid = _validate_upload_filename(file.filename or "")
        upload_kind = "audio"
    cleaned_summary_preset = options.summary_preset
    cleaned_summary_profile = options.summary_profile
    cleaned_summary_prompt_template = options.summary_prompt_template

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

    input_path = upload_path
    if open_public and upload_kind == "video":
        try:
            input_path = _convert_video_upload_to_audio(upload_path)
        except HTTPException:
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise

    try:
        job = _create_job(
            skip_summary=skip_summary,
            summary_preset=cleaned_summary_preset,
            summary_profile=cleaned_summary_profile,
            summary_prompt_template=cleaned_summary_prompt_template,
            auto_generate_fancy_html=auto_generate_fancy_html,
        )
    except JobCapacityError as exc:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise HTTPException(status_code=429, detail=str(exc)) from None
    job_id = str(job["job_id"])
    input_bvid = f"upload-{job_id}" if open_public else bvid
    submitted = job_manager.submit(
        job_id,
        _run_job,
        submitter=submit_job,
        job_id=job_id,
        url=None,
        input_audio_path=str(input_path),
        input_bvid=input_bvid,
        ephemeral_upload=open_public,
        skip_summary=skip_summary,
        summary_preset=cleaned_summary_preset,
        summary_profile=cleaned_summary_profile,
        summary_prompt_template=cleaned_summary_prompt_template,
        auto_generate_fancy_html=auto_generate_fancy_html,
        **options.runtime_config_kwargs(),
    )
    if submitted is None:
        shutil.rmtree(temp_dir, ignore_errors=True)

    return ProcessStartResponse(job_id=job_id)


@router.get("/api/jobs/active", response_model=ActiveJobsResponse)
def list_active_jobs() -> ActiveJobsResponse:
    jobs = _list_active_jobs()
    return ActiveJobsResponse(jobs=[ActiveJobItem(**j) for j in jobs])


def _serialize_sse(event: str, payload: object) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _job_snapshots_response(job_ids: tuple[str, ...]) -> JobSnapshotsResponse:
    jobs = [job for job_id in job_ids if (job := _get_job(job_id)) is not None]
    return JobSnapshotsResponse(jobs=[_to_process_status_response(job) for job in jobs])


def _process_response_is_active(response: ProcessStatusResponse) -> bool:
    if response.status in {"queued", "running"}:
        return True
    return (
        response.status == "succeeded"
        and response.auto_generate_fancy_html
        and (response.fancy_html_status in {"pending", "running"})
    )


@router.get("/api/jobs/events")
async def active_job_events(
    job_id: Annotated[list[str], Query()],
) -> StreamingResponse:
    job_ids = tuple(dict.fromkeys(value for value in job_id if value))
    if not job_ids:
        raise HTTPException(status_code=400, detail="至少需要一个任务 ID")

    async def stream() -> AsyncIterator[str]:
        subscription = event_broker.subscribe(job_channel(value) for value in job_ids)
        try:
            while True:
                response = _job_snapshots_response(job_ids)
                yield _serialize_sse("jobs", response.model_dump(mode="json"))
                if not any(_process_response_is_active(job) for job in response.jobs):
                    return
                if not await subscription.wait():
                    yield ": keep-alive\n\n"
        finally:
            subscription.close()

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )


@router.post("/api/process/{job_id}/cancel")
def cancel_job(job_id: str) -> dict:
    cancelled, status = job_manager.cancel(job_id)
    if status is None:
        raise HTTPException(status_code=404, detail="任务不存在或已过期")
    if not cancelled:
        raise HTTPException(
            status_code=400,
            detail=f"只能取消进行中的任务（当前状态：{status}）",
        )
    return {"ok": True, "job_id": job_id}


def _to_process_status_response(job: dict) -> ProcessStatusResponse:
    return ProcessStatusResponse.model_validate(job)


@router.get("/api/process/{job_id}/events")
async def process_events(job_id: str) -> StreamingResponse:
    if _get_job(job_id) is None:
        raise HTTPException(status_code=404, detail="任务不存在或已过期")

    async def stream() -> AsyncIterator[str]:
        subscription = event_broker.subscribe([job_channel(job_id)])
        try:
            while True:
                job = _get_job(job_id)
                if job is None:
                    yield _serialize_sse("deleted", {"job_id": job_id})
                    return
                response = _to_process_status_response(job)
                yield _serialize_sse("job", response.model_dump(mode="json"))
                fancy_html_active = response.auto_generate_fancy_html and (
                    response.fancy_html_status in {"pending", "running"}
                )
                if response.status in {"failed", "cancelled"} or (
                    response.status == "succeeded" and not fancy_html_active
                ):
                    return
                while not await subscription.wait():
                    yield ": keep-alive\n\n"
        finally:
            subscription.close()

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )


@router.get("/api/process/{job_id}", response_model=ProcessStatusResponse)
def process_status(job_id: str) -> ProcessStatusResponse:
    job = _get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在或已过期")
    return _to_process_status_response(job)
