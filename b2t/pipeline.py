"""Main pipeline orchestration"""

import json
import logging
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path
from uuid import uuid4

from dataclasses import replace

from b2t.config import (
    AppConfig,
    flatten_stt_profile,
    resolve_stt_profile,
)
from b2t.converter.json_to_md import convert_json_to_md
from b2t.config import AppConfig
from b2t.converter.json_to_md import TIMELINE_SCHEMA_VERSION, convert_json_to_md
from b2t.download.metadata import get_video_metadata
from b2t.download.subtitle import fetch_bilibili_subtitle
from b2t.download.yutto import download_audio
from b2t.download.yutto_cli import (
    extract_bilibili_target_id,
    extract_bvid,
    normalize_bilibili_target,
)
from b2t.storage import (
    StorageBackend,
    StoredArtifact,
    create_storage_backend,
    create_stt_storage_backend,
)
from b2t.stt import create_stt_provider
from b2t.summarize.llm import summarize
from b2t.summarize.timeline import (
    export_summary_table_without_video_time,
    export_summary_timeline_text,
)

logger = logging.getLogger(__name__)


def _ensure_bvid_prefixed_name(name: str, bvid: str) -> str:
    lowered = name.lower()
    bvid_lower = bvid.lower()
    if lowered.startswith(bvid_lower):
        return name
    return f"{bvid}_{name}"


def _safe_path_name(name: str) -> str:
    cleaned = "".join("_" if char in '<>:"/\\|?*' else char for char in name)
    cleaned = cleaned.strip(" .")
    return cleaned or "untitled"


def run_pipeline(
    url: str,
    config: AppConfig,
    *,
    audio_path: Path | str | None = None,
    input_bvid: str | None = None,
    skip_summary: bool = False,
    summary_preset: str | None = None,
    summary_profile: str | None = None,
    summary_prompt_template: str | None = None,
    stt_profile: str | None = None,
    output_dir: Path | str | None = None,
    progress_callback: Callable[[str, str, int], None] | None = None,
    storage_backend: "StorageBackend | None" = None,
    stt_storage_backend: "StorageBackend | None" = None,
    prefer_bilibili_subtitle: bool = True,
    bilibili_subtitle_used_callback: Callable[[], None] | None = None,
) -> dict[str, StoredArtifact]:
    """Run the full transcription pipeline

    Pipeline: obtain transcript (Bilibili subtitle or ASR) -> Markdown -> summarize

    Args:
        url: Bilibili video URL (required when audio_path is None)
        config: Application config
        audio_path: Local audio path (skip download when provided)
        input_bvid: Optional BV ID, takes priority over URL/filename extraction
        skip_summary: Whether to skip LLM summarization
        summary_preset: Summary preset name, uses config default when None
        summary_profile: Summary model profile name, uses config default when None
        summary_prompt_template: Optional request-scoped prompt template override
        output_dir: Output root directory, uses config download.output_dir when None
        progress_callback: Stage progress callback with (stage_key, stage_label, progress_percent)
        prefer_bilibili_subtitle: Try Bilibili native subtitles before downloading
            audio. Ignored for local uploads.

    Returns:
        Storage info for output files from each stage:
        - "audio": Audio file (only when ASR path is used)
        - "json": Transcription JSON
        - "markdown": Original Markdown
        - "summary": Summary Markdown (excluded when skip_summary is True)
        - "summary_table_md": Summary table Markdown (included when table exists)
    """
    results: dict[str, StoredArtifact] = {}
    local_results: dict[str, Path] = {}
    if storage_backend is None:
        storage_backend = create_storage_backend(config)
    if stt_storage_backend is None:
        stt_storage_backend = create_stt_storage_backend(config)

    if storage_backend.persist_local_outputs:
        transcribe_root = Path(output_dir or config.download.output_dir)
        transcribe_root.mkdir(parents=True, exist_ok=True)
    else:
        transcribe_root = Path(tempfile.mkdtemp(prefix="b2t-"))

    temp_download_dir = transcribe_root / "temp_download"
    temp_download_dir.mkdir(exist_ok=True)

    def emit_progress(stage: str, label: str, progress: int) -> None:
        if progress_callback is not None:
            progress_callback(stage, label, progress)

    try:
        normalized_audio_path = (
            Path(audio_path).expanduser().resolve() if audio_path is not None else None
        )
        use_local_audio = normalized_audio_path is not None
        subtitle = None
        if use_local_audio:
            if not normalized_audio_path.is_file():
                raise FileNotFoundError(f"上传音频文件不存在: {normalized_audio_path}")
            emit_progress("downloading", "处理上传音频", 10)
            logger.info("=== 处理上传音频 ===")
            audio_file = normalized_audio_path
            metadata = None
            bvid = input_bvid or extract_bvid(audio_file.name)
            transcription_id = bvid
        else:
            if not url.strip():
                raise ValueError("URL 不能为空")
            normalized_url = normalize_bilibili_target(url)
            bvid = input_bvid or extract_bvid(normalized_url)
            transcription_id = extract_bilibili_target_id(normalized_url) or bvid
            metadata = None
            if bvid:
                try:
                    metadata = get_video_metadata(bvid)
                except Exception as e:
                    logger.warning("Failed to fetch video metadata: %s", e)

            if prefer_bilibili_subtitle:
                emit_progress("downloading", "获取 B 站字幕", 10)
                logger.info("=== 获取 B 站字幕 ===")
                subtitle = fetch_bilibili_subtitle(normalized_url)
            else:
                subtitle = None

            if subtitle is None:
                emit_progress("downloading", "下载视频音频", 10)
                logger.info("=== 下载音频 ===")
                audio_file, downloaded_metadata = download_audio(
                    normalized_url,
                    temp_download_dir,
                    config.download.audio_quality,
                    fetch_metadata=metadata is None,
                )
                if metadata is None:
                    metadata = downloaded_metadata
                bvid = bvid or extract_bvid(audio_file.name)
            else:
                audio_file = None

        if bvid is None:
            raise ValueError(
                "无法提取 BV 号。请使用包含 BV 号的 URL，"
                "或上传形如 `BV号_视频标题.xxx` 的音频文件。"
            )
        if transcription_id is None:
            transcription_id = bvid

        # Record metadata
        if metadata:
            logger.info(
                "Video author: %s, publish date: %s", metadata.author, metadata.pubdate
            )
            results["_metadata"] = metadata  # Temporarily store metadata for later use

        # Create workflow directory
        if audio_file is None:
            work_dir_name = (
                f"{transcription_id}_{_safe_path_name(metadata.title)}"
                if metadata and metadata.title
                else transcription_id
            )
        else:
            work_dir_name = audio_file.stem
        work_dir = transcribe_root / _ensure_bvid_prefixed_name(
            work_dir_name, transcription_id
        )
        work_dir.mkdir(exist_ok=True)

        if audio_file is None:
            if bilibili_subtitle_used_callback is not None:
                bilibili_subtitle_used_callback()
            emit_progress("converting", "Generating Markdown", 80)
            logger.info("Work directory: %s", work_dir)
            logger.info("Using Bilibili native subtitle")
            json_path = work_dir / f"{work_dir.name}_transcription.json"
            subtitle_payload: dict[str, object] = {
                "text": subtitle.text,
                "source": "bilibili_subtitle",
                "bvid": bvid,
                "timeline_schema_version": TIMELINE_SCHEMA_VERSION,
            }
            if subtitle.items:
                subtitle_payload["segments"] = [
                    {
                        "start": item.start_ms / 1000,
                        "end": item.end_ms / 1000,
                        "text": item.text,
                    }
                    for item in subtitle.items
                ]
            json_path.write_text(
                json.dumps(subtitle_payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        else:
            # Move audio to work directory
            audio_filename = _ensure_bvid_prefixed_name(
                audio_file.name, transcription_id
            )
            new_audio_path = work_dir / audio_filename
            if use_local_audio:
                shutil.copy2(str(audio_file), new_audio_path)
            else:
                shutil.move(str(audio_file), new_audio_path)
            local_results["audio"] = new_audio_path
            logger.info("Work directory: %s", work_dir)

            # 2. Transcribe (each provider handles its own details, e.g. Qwen's OSS upload)
            if stt_profile is not None:
                resolved_stt = resolve_stt_profile(config.stt, override=stt_profile)
                config = replace(
                    config,
                    stt=flatten_stt_profile(config.stt, resolved_stt, stt_profile),
                )
            stt_provider = create_stt_provider(config, stt_storage_backend)
            json_path = stt_provider.transcribe(
                new_audio_path,
                work_dir,
                progress_callback=emit_progress,
            )
            transcription_payload = json.loads(json_path.read_text(encoding="utf-8"))
            if not isinstance(transcription_payload, dict):
                raise ValueError("转录结果 JSON 顶层必须是对象")
            transcription_payload["timeline_schema_version"] = TIMELINE_SCHEMA_VERSION
            json_path.write_text(
                json.dumps(transcription_payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        local_results["json"] = json_path

        # 3. JSON -> Markdown
        emit_progress("converting", "Generating Markdown", 80)
        logger.info("=== Generating Markdown ===")
        md_path = convert_json_to_md(json_path, min_length=config.converter.min_length)
        local_results["markdown"] = md_path

        # 4. LLM Summarization
        if not skip_summary:
            emit_progress("summarizing", "LLM summarization", 90)
            logger.info("=== Generating summary ===")
            summary_path = summarize(
                md_path,
                config.summarize,
                config.summary_presets,
                summary_context_config=config.summary_context,
                preset=summary_preset,
                profile=summary_profile,
                prompt_template_override=summary_prompt_template,
                metadata=metadata,
            )
            local_results["summary"] = summary_path

            # Extract summary table as a separate Markdown file
            summary_table_md_path = export_summary_table_without_video_time(
                summary_path
            )
            if summary_table_md_path is not None:
                local_results["summary_table_md"] = summary_table_md_path
            summary_timeline_path = export_summary_timeline_text(summary_path)
            if summary_timeline_path is not None:
                local_results["summary_timeline"] = summary_timeline_path

        storage_prefix = f"{transcription_id}-{uuid4().hex[:8]}"
        for artifact_key, artifact_path in local_results.items():
            object_key = f"{storage_prefix}/{artifact_path.name}"
            results[artifact_key] = storage_backend.store_file(
                artifact_path,
                object_key=object_key,
            )

        emit_progress("completed", "处理完成", 100)
        logger.info(
            "所有文件已写入 %s backend，工作目录: %s",
            storage_backend.backend_name,
            work_dir,
        )

    finally:
        # Clean up temp download directory
        if temp_download_dir.exists():
            shutil.rmtree(temp_download_dir)
        # When using MinIO backend with temp directory, clean up all local files after pipeline
        if not storage_backend.persist_local_outputs and transcribe_root.exists():
            shutil.rmtree(transcribe_root, ignore_errors=True)

    return results
