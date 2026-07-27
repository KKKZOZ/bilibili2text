"""Business logic helpers: artifact building, summary execution, and history recording."""

import logging
import tempfile
from collections.abc import Mapping
from pathlib import Path
from uuid import uuid4

from b2t.config import (
    AppConfig,
    resolve_summarize_model_profile,
    resolve_summary_preset_name,
)
from b2t.converter.md_remove_table import MarkdownRemoveTableConverter
from b2t.converter.md_to_png import MarkdownToPngConverter
from b2t.download.metadata import VideoMetadata
from b2t.history import HistoryArtifact, infer_run_id, record_pipeline_run
from b2t.storage import StorageBackend, StoredArtifact
from b2t.storage.base import classify_artifact_filename
from b2t.summarize.fancy_html import generate_fancy_summary_html
from b2t.summarize.llm import (
    summarize,
)
from b2t.summarize.timeline import (
    export_summary_table_without_video_time,
    export_summary_timeline_text,
)
from backend.dependencies import get_history_db
from backend.download_registry import download_registry
from backend.stock_cache import get_cached_stock_statuses, get_or_fetch_stock_statuses

logger = logging.getLogger(__name__)
CUSTOM_SUMMARY_PRESET_VALUE = "__user_custom__"
_XIAOYUZHOU_BVID_PREFIX = "xiaoyuzhou_"
_MISSING_METADATA_TEXT = {"", "unknown"}


def _clean_metadata_text(value: object) -> str:
    text = str(value or "").strip()
    if text.lower() in _MISSING_METADATA_TEXT:
        return ""
    return text


def _history_detail_for_existing_results(
    *,
    bvid: str,
    existing_results: Mapping[str, object],
) -> object | None:
    markdown_artifact = existing_results.get("markdown")
    if not isinstance(markdown_artifact, StoredArtifact):
        return None
    try:
        return get_history_db().get_run_detail(
            infer_run_id(markdown_artifact.storage_key, bvid=bvid)
        )
    except Exception as exc:
        logger.debug("读取历史元信息失败: %s", exc)
        return None


def _fetch_platform_metadata_for_bvid(bvid: str) -> VideoMetadata | None:
    if not bvid.startswith(_XIAOYUZHOU_BVID_PREFIX):
        return None

    episode_id = bvid.removeprefix(_XIAOYUZHOU_BVID_PREFIX).strip()
    if not episode_id:
        return None

    try:
        from b2t.download.metadata import VideoMetadata as PlatformVideoMetadata
        from b2t.download.xiaoyuzhou import fetch_xiaoyuzhou_metadata

        return PlatformVideoMetadata.from_platform_metadata(
            fetch_xiaoyuzhou_metadata(episode_id)
        )
    except Exception as exc:
        logger.warning("补取小宇宙元信息失败（将继续使用历史字段）: %s", exc)
        return None


def _resolve_existing_video_metadata(
    *,
    bvid: str,
    existing_results: Mapping[str, object],
    title: str = "",
    author: str = "",
    pubdate: str = "",
) -> VideoMetadata | None:
    """Resolve metadata for reused transcriptions without redownloading audio."""
    resolved_title = _clean_metadata_text(title)
    resolved_author = _clean_metadata_text(author)
    resolved_pubdate = _clean_metadata_text(pubdate)
    pubdate_timestamp = 0

    if not (resolved_title and resolved_author and resolved_pubdate):
        detail = _history_detail_for_existing_results(
            bvid=bvid,
            existing_results=existing_results,
        )
        if detail is not None:
            resolved_title = resolved_title or _clean_metadata_text(
                getattr(detail, "title", "")
            )
            resolved_author = resolved_author or _clean_metadata_text(
                getattr(detail, "author", "")
            )
            resolved_pubdate = resolved_pubdate or _clean_metadata_text(
                getattr(detail, "pubdate", "")
            )

    platform_metadata = None
    if not (resolved_title and resolved_author and resolved_pubdate):
        platform_metadata = _fetch_platform_metadata_for_bvid(bvid)
        if platform_metadata is not None:
            resolved_title = resolved_title or _clean_metadata_text(
                platform_metadata.title
            )
            resolved_author = resolved_author or _clean_metadata_text(
                platform_metadata.author
            )
            resolved_pubdate = resolved_pubdate or _clean_metadata_text(
                platform_metadata.pubdate
            )
            if resolved_pubdate == _clean_metadata_text(platform_metadata.pubdate):
                pubdate_timestamp = platform_metadata.pubdate_timestamp

    if not (resolved_title or resolved_author or resolved_pubdate):
        return None

    return VideoMetadata(
        bvid=bvid,
        title=resolved_title,
        author=resolved_author,
        author_uid=0,
        pubdate=resolved_pubdate,
        pubdate_timestamp=pubdate_timestamp,
        description="",
    )


def _should_refresh_existing_summary_metadata(
    *,
    bvid: str,
    existing_results: Mapping[str, object],
) -> bool:
    """Return True when an old cached summary likely has Unknown metadata header."""
    if not bvid.startswith(_XIAOYUZHOU_BVID_PREFIX):
        return False

    detail = _history_detail_for_existing_results(
        bvid=bvid,
        existing_results=existing_results,
    )
    if detail is None:
        return True

    return not (
        _clean_metadata_text(getattr(detail, "author", ""))
        and _clean_metadata_text(getattr(detail, "pubdate", ""))
    )


def _resolve_summary_selection(
    *,
    config: AppConfig | None,
    has_summary: bool,
    summary_preset: str | None,
    summary_profile: str | None,
) -> tuple[str | None, str | None]:
    if not has_summary:
        return None, None

    cleaned_preset = (summary_preset or "").strip() or None
    cleaned_profile = (summary_profile or "").strip() or None
    if config is None:
        return cleaned_preset, cleaned_profile

    if cleaned_preset == CUSTOM_SUMMARY_PRESET_VALUE:
        resolved_preset = CUSTOM_SUMMARY_PRESET_VALUE
    else:
        resolved_preset = resolve_summary_preset_name(
            summarize=config.summarize,
            summary_presets=config.summary_presets,
            override=cleaned_preset,
        )
    resolved_profile = cleaned_profile or config.summarize.profile.strip()
    resolve_summarize_model_profile(
        config.summarize,
        override=resolved_profile,
    )
    return resolved_preset, resolved_profile


def _build_success_download_fields(
    results: dict[str, StoredArtifact],
) -> dict[str, str | None]:
    md_artifact = results.get("markdown")
    if md_artifact is None:
        raise ValueError("未生成 Markdown 文件")

    payload: dict[str, str | None] = {
        "download_url": f"/api/download/{download_registry.store_artifact(md_artifact)}",
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
        payload["txt_download_url"] = (
            f"/api/download/{download_registry.store_artifact(txt_artifact)}"
        )
        payload["txt_filename"] = txt_artifact.filename

    summary_artifact = results.get("summary")
    if summary_artifact is not None:
        payload["summary_download_url"] = (
            f"/api/download/{download_registry.store_artifact(summary_artifact)}"
        )
        payload["summary_filename"] = summary_artifact.filename

    summary_txt_artifact = results.get("summary_text")
    if summary_txt_artifact is not None:
        payload["summary_txt_download_url"] = (
            f"/api/download/{download_registry.store_artifact(summary_txt_artifact)}"
        )
        payload["summary_txt_filename"] = summary_txt_artifact.filename

    summary_table_pdf_artifact = results.get("summary_table_pdf")
    if summary_table_pdf_artifact is not None:
        payload["summary_table_pdf_download_url"] = (
            f"/api/download/{download_registry.store_artifact(summary_table_pdf_artifact)}"
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

        download_id = download_registry.store_artifact(artifact)
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
    with (
        storage_backend.open_stream(artifact.storage_key) as stream,
        target_path.open("wb") as output,
    ):
        while True:
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            output.write(chunk)
    return target_path


def _storage_parent_key(storage_key: str) -> str:
    normalized = storage_key.replace("\\", "/").strip("/")
    if "/" not in normalized:
        return ""
    return normalized.rsplit("/", 1)[0]


def _artifact_sibling_object_key(
    *,
    storage_backend: StorageBackend,
    config: AppConfig,
    source_storage_key: str,
    filename: str,
) -> str:
    parent_key = _storage_parent_key(source_storage_key)
    if storage_backend.backend_name == "minio":
        base_prefix = config.storage.minio.base_prefix.strip("/")
        if base_prefix and parent_key.startswith(f"{base_prefix}/"):
            parent_key = parent_key[len(base_prefix) + 1 :]
    elif storage_backend.backend_name == "alicloud":
        base_prefix = config.storage.alicloud.base_prefix.strip("/")
        if base_prefix and parent_key.startswith(f"{base_prefix}/"):
            parent_key = parent_key[len(base_prefix) + 1 :]

    return f"{parent_key}/{filename}" if parent_key else filename


def _store_sibling_artifact(
    *,
    storage_backend: StorageBackend,
    config: AppConfig,
    source_artifact: StoredArtifact,
    path: Path,
) -> StoredArtifact:
    object_key = _artifact_sibling_object_key(
        storage_backend=storage_backend,
        config=config,
        source_storage_key=source_artifact.storage_key,
        filename=path.name,
    )
    return storage_backend.store_file(path, object_key=object_key)


def _generate_summary_png_exports(
    *,
    results: dict[str, StoredArtifact],
    storage_backend: StorageBackend,
    config: AppConfig,
    refresh_stock_statuses: bool = False,
    stock_status_timeout_seconds: float | None = None,
    include_no_table: bool = True,
) -> dict[str, StoredArtifact]:
    summary_artifact = results.get("summary")
    if summary_artifact is None:
        return {}
    metadata = results.get("_metadata")
    as_of_date = getattr(metadata, "pubdate", "") if metadata is not None else ""

    cleanup_temp_dir: tempfile.TemporaryDirectory | None = None
    local_temp_dir: Path | None = None
    if storage_backend.persist_local_outputs:
        work_root = Path(config.download.output_dir).expanduser().resolve()
        work_root.mkdir(parents=True, exist_ok=True)
        work_dir = work_root / f".tmp-png-export-{uuid4().hex[:8]}"
        work_dir.mkdir(parents=True, exist_ok=False)
        local_temp_dir = work_dir
    else:
        cleanup_temp_dir = tempfile.TemporaryDirectory(prefix="b2t-png-export-")
        work_dir = Path(cleanup_temp_dir.name)

    generated: dict[str, StoredArtifact] = {}
    try:
        summary_path = _materialize_artifact_to_file(
            storage_backend,
            summary_artifact,
            work_dir,
        )
        summary_table_artifact = results.get("summary_table_md")
        table_md_path = (
            _materialize_artifact_to_file(
                storage_backend,
                summary_table_artifact,
                work_dir,
            )
            if summary_table_artifact is not None
            else None
        )
        bvid = getattr(metadata, "bvid", "") if metadata is not None else ""
        stock_statuses = {}
        if bvid:
            try:
                markdown_paths = [
                    path for path in (summary_path, table_md_path) if path is not None
                ]
                if refresh_stock_statuses or stock_status_timeout_seconds is not None:
                    stock_statuses = get_or_fetch_stock_statuses(
                        db=get_history_db(),
                        bvid=bvid,
                        as_of_date=as_of_date,
                        markdown_paths=markdown_paths,
                        timeout_seconds=stock_status_timeout_seconds,
                    )
                else:
                    stock_statuses = get_cached_stock_statuses(
                        db=get_history_db(),
                        bvid=bvid,
                        as_of_date=as_of_date,
                        markdown_paths=markdown_paths,
                    )
            except Exception as exc:
                logger.warning(
                    "股票状态缓存读取失败，导出将不展示实时行情: %s",
                    exc,
                )

        if refresh_stock_statuses and not stock_statuses:
            logger.info("后台行情刷新未获得可用数据，保留现有导出文件")
            return {}

        png_converter = MarkdownToPngConverter()

        summary_png_path = summary_path.with_suffix(".png")
        png_converter.convert(
            summary_path,
            summary_png_path,
            is_table=False,
            as_of_date=as_of_date,
            enhance_stock_tables=True,
            stock_statuses=stock_statuses,
            dpr=4,
        )
        generated["summary_png"] = _store_sibling_artifact(
            storage_backend=storage_backend,
            config=config,
            source_artifact=summary_artifact,
            path=summary_png_path,
        )

        if include_no_table:
            no_table_md_path = summary_path.with_stem(f"{summary_path.stem}_no_table")
            MarkdownRemoveTableConverter().convert(summary_path, no_table_md_path)
            no_table_png_path = no_table_md_path.with_suffix(".png")
            png_converter.convert(no_table_md_path, no_table_png_path, is_table=False)
            generated["summary_no_table_png"] = _store_sibling_artifact(
                storage_backend=storage_backend,
                config=config,
                source_artifact=summary_artifact,
                path=no_table_png_path,
            )

        if summary_table_artifact is not None and table_md_path is not None:
            table_png_path = table_md_path.with_suffix(".png")
            png_converter.convert(
                table_md_path,
                table_png_path,
                is_table=True,
                as_of_date=as_of_date,
                stock_statuses=stock_statuses,
            )
            generated["summary_table_png"] = _store_sibling_artifact(
                storage_backend=storage_backend,
                config=config,
                source_artifact=summary_table_artifact,
                path=table_png_path,
            )
    finally:
        if cleanup_temp_dir is not None:
            cleanup_temp_dir.cleanup()
        if local_temp_dir is not None and local_temp_dir.exists():
            for path in local_temp_dir.iterdir():
                if path.is_file():
                    path.unlink(missing_ok=True)
            local_temp_dir.rmdir()

    return generated


def _run_summary_only_from_existing(
    *,
    bvid: str,
    transcription_id: str | None = None,
    storage_backend: StorageBackend,
    config: AppConfig,
    existing_results: Mapping[str, object],
    summary_preset: str | None,
    summary_profile: str | None,
    summary_prompt_template: str | None = None,
    title: str = "",
    author: str = "",
    pubdate: str = "",
) -> dict[str, object]:
    markdown_artifact = existing_results.get("markdown")
    if markdown_artifact is None:
        raise ValueError("历史转录结果中缺少 Markdown 文件，无法仅执行总结步骤")

    metadata = _resolve_existing_video_metadata(
        bvid=bvid,
        existing_results=existing_results,
        title=title,
        author=author,
        pubdate=pubdate,
    )

    run_prefix = f"{transcription_id or bvid}-{uuid4().hex[:8]}"
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
            summary_context_config=config.summary_context,
            preset=summary_preset,
            profile=summary_profile,
            prompt_template_override=summary_prompt_template,
            metadata=metadata,
        )

        summary_table_md: Path | None = None
        try:
            summary_table_md = export_summary_table_without_video_time(summary_path)
        except Exception as exc:
            logger.warning("总结表格 Markdown 导出失败，已跳过: %s", exc)

        results: dict[str, object] = {}
        results["summary"] = storage_backend.store_file(
            summary_path,
            object_key=f"{run_prefix}/{summary_path.name}",
        )
        if summary_table_md is not None:
            results["summary_table_md"] = storage_backend.store_file(
                summary_table_md,
                object_key=f"{run_prefix}/{summary_table_md.name}",
            )
        summary_timeline = export_summary_timeline_text(summary_path)
        if summary_timeline is not None:
            results["summary_timeline"] = storage_backend.store_file(
                summary_timeline,
                object_key=f"{run_prefix}/{summary_timeline.name}",
            )
        if metadata is not None:
            results["_metadata"] = metadata

        # Local backend temporarily copies markdown for summary only, to avoid polluting the history file list.
        if storage_backend.persist_local_outputs:
            markdown_path.unlink(missing_ok=True)

        return results
    finally:
        if cleanup_temp_dir is not None:
            cleanup_temp_dir.cleanup()


def _run_fancy_html_only_from_summary(
    *,
    summary_artifact: StoredArtifact,
    storage_backend: StorageBackend,
    config: AppConfig,
    summary_profile: str | None,
) -> StoredArtifact:
    if classify_artifact_filename(summary_artifact.filename) not in (
        "summary",
        "rag_answer",
    ):
        raise ValueError("仅支持基于总结 Markdown 或知识库回答生成 fancy HTML")

    cleanup_temp_dir: tempfile.TemporaryDirectory | None = None
    local_temp_dir: Path | None = None
    if storage_backend.persist_local_outputs:
        work_root = Path(config.download.output_dir).expanduser().resolve()
        work_root.mkdir(parents=True, exist_ok=True)
        work_dir = work_root / f".tmp-fancy-{uuid4().hex[:8]}"
        work_dir.mkdir(parents=True, exist_ok=False)
        local_temp_dir = work_dir
    else:
        cleanup_temp_dir = tempfile.TemporaryDirectory(prefix="b2t-fancy-html-")
        work_dir = Path(cleanup_temp_dir.name)

    try:
        summary_path = _materialize_artifact_to_file(
            storage_backend,
            summary_artifact,
            work_dir,
        )
        fancy_html_path = generate_fancy_summary_html(
            summary_path,
            config,
            profile=summary_profile,
        )

        object_key = _artifact_sibling_object_key(
            storage_backend=storage_backend,
            config=config,
            source_storage_key=summary_artifact.storage_key,
            filename=fancy_html_path.name,
        )
        stored = storage_backend.store_file(
            fancy_html_path,
            object_key=object_key,
        )
        if storage_backend.persist_local_outputs:
            summary_path.unlink(missing_ok=True)
            fancy_html_path.unlink(missing_ok=True)
        return stored
    finally:
        if cleanup_temp_dir is not None:
            cleanup_temp_dir.cleanup()
        if local_temp_dir is not None:
            for path in local_temp_dir.iterdir():
                if path.is_file():
                    path.unlink(missing_ok=True)
            local_temp_dir.rmdir()


def _merge_history_artifact(
    *,
    run_id: str,
    bvid: str,
    artifact: StoredArtifact,
    title: str = "",
    author: str = "",
    pubdate: str = "",
    created_at: str | None = None,
    summary_preset: str | None = None,
    summary_profile: str | None = None,
    fancy_html_status: str | None = None,
    fancy_html_error: str | None = None,
) -> object | None:
    try:
        db = get_history_db()
    except Exception as exc:
        logger.warning("无法初始化历史数据库，跳过 fancy HTML 归档: %s", exc)
        return None

    detail = db.get_run_detail(run_id)
    if detail is None:
        inferred_title = title or bvid
        db.record_run(
            run_id=run_id,
            bvid=bvid,
            title=inferred_title,
            author=author,
            pubdate=pubdate,
            created_at=created_at,
            has_summary=True,
            artifacts=[
                HistoryArtifact(
                    kind=classify_artifact_filename(artifact.filename) or "file",
                    filename=artifact.filename,
                    storage_key=artifact.storage_key,
                    backend=artifact.backend,
                    summary_preset=(summary_preset or "").strip(),
                    summary_profile=(summary_profile or "").strip(),
                )
            ],
            fancy_html_status=fancy_html_status,
            fancy_html_error=fancy_html_error,
        )
        return db.get_run_detail(run_id)

    merged_artifacts = list(detail.artifacts)
    if not any(item.storage_key == artifact.storage_key for item in merged_artifacts):
        merged_artifacts.append(
            HistoryArtifact(
                kind=classify_artifact_filename(artifact.filename) or "file",
                filename=artifact.filename,
                storage_key=artifact.storage_key,
                backend=artifact.backend,
                summary_preset=(summary_preset or "").strip(),
                summary_profile=(summary_profile or "").strip(),
            )
        )
    has_summary = any(
        item.kind
        in {
            "summary",
            "summary_text",
            "summary_fancy_html",
            "summary_png",
            "summary_no_table_png",
            "summary_table_md",
            "summary_table_png",
            "summary_table_pdf",
            "summary_timeline",
        }
        for item in merged_artifacts
    )
    db.record_run(
        run_id=detail.run_id,
        bvid=detail.bvid,
        title=detail.title,
        author=detail.author,
        pubdate=detail.pubdate,
        created_at=detail.created_at,
        has_summary=has_summary,
        artifacts=merged_artifacts,
        record_type=detail.record_type,
        fancy_html_status=fancy_html_status,
        fancy_html_error=fancy_html_error,
    )
    return db.get_run_detail(run_id)


def _artifact_download_item(artifact: StoredArtifact) -> dict[str, str]:
    return {
        "url": f"/api/download/{download_registry.store_artifact(artifact)}",
        "filename": artifact.filename,
        "kind": classify_artifact_filename(artifact.filename) or "file",
    }


def _record_history(
    *,
    bvid: str,
    results: dict[str, object],
    created_at: str | None = None,
    config: AppConfig | None = None,
    summary_preset: str | None = None,
    summary_profile: str | None = None,
) -> str | None:
    """Record a completed transcription run to the history DB.

    Returns the run_id if successful, None otherwise.
    """
    try:
        db = get_history_db()
    except Exception as exc:
        logger.warning("无法初始化历史数据库，跳过记录: %s", exc)
        return None

    try:
        # Extract metadata from results
        metadata = results.get("_metadata")
        if not isinstance(metadata, VideoMetadata):
            metadata = _resolve_existing_video_metadata(
                bvid=bvid,
                existing_results=results,
            )
        author = metadata.author if metadata else ""
        pubdate = metadata.pubdate if metadata else ""
        file_results = {
            key: value
            for key, value in results.items()
            if not key.startswith("_") and isinstance(value, StoredArtifact)
        }
        has_summary = "summary" in file_results
        resolved_preset, resolved_profile = _resolve_summary_selection(
            config=config,
            has_summary=has_summary,
            summary_preset=summary_preset,
            summary_profile=summary_profile,
        )

        return record_pipeline_run(
            db=db,
            bvid=bvid,
            results=file_results,
            author=author,
            pubdate=pubdate,
            created_at=created_at,
            summary_preset=resolved_preset,
            summary_profile=resolved_profile,
            merge_existing_artifacts=True,
        )
    except Exception as exc:
        logger.warning("记录历史转录失败: %s", exc)
        return None
