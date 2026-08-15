"""Business logic helpers: artifact building, summary execution, and history recording."""

import logging
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from b2t.cancellation import CancellationToken, PipelineCancelled
from b2t.config import (
    AppConfig,
    build_bilibili_cookie,
    resolve_summarize_model_profile,
    resolve_summary_preset_name,
)
from b2t.converter.md_remove_table import MarkdownRemoveTableConverter
from b2t.converter.md_to_png import MarkdownToPngConverter
from b2t.download.comments import (
    DEFAULT_COMMENT_LIMIT,
    comment_platform_from_metadata,
    comment_platform_label,
    count_comment_replies,
    count_up_replies,
    fetch_platform_comments,
    write_comments_json,
    write_comments_markdown,
)
from b2t.download.metadata import VideoMetadata
from b2t.download.platform import Platform, build_transcription_artifact_name
from b2t.history import HistoryArtifact, infer_run_id, record_pipeline_run
from b2t.storage import (
    SUMMARY_ARTIFACT_KINDS,
    ArtifactKind,
    StorageBackend,
    StoredArtifact,
)
from b2t.storage.base import resolve_artifact_kind
from b2t.summarize.fancy_html import generate_fancy_summary_html
from b2t.summarize.llm import (
    summarize_with_comment_viewpoints,
)
from b2t.summarize.timeline import (
    export_summary_table_without_video_time,
    export_summary_timeline_text,
)
from backend.artifacts import materialize_artifact, storage_parent_key
from backend.dependencies import get_history_db
from backend.download_registry import download_registry
from backend.stock_cache import get_cached_stock_statuses, get_or_fetch_stock_statuses

logger = logging.getLogger(__name__)
CUSTOM_SUMMARY_PRESET_VALUE = "__user_custom__"
_MISSING_METADATA_TEXT = {"", "unknown"}


def _xiaoyuzhou_episode_id(bvid: str) -> str | None:
    prefix = f"{Platform.XIAOYUZHOU.value}_"
    if not bvid.startswith(prefix):
        return None
    return bvid.removeprefix(prefix).strip() or None


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
    if bvid.startswith("BV"):
        try:
            from b2t.download.metadata import get_video_metadata

            return get_video_metadata(bvid)
        except Exception as exc:
            logger.warning("补取 Bilibili 元信息失败（将继续使用历史字段）: %s", exc)
            return None

    episode_id = _xiaoyuzhou_episode_id(bvid)
    if episode_id is None:
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
    require_platform_metadata: bool = False,
) -> VideoMetadata | None:
    """Resolve metadata for reused transcriptions without redownloading audio."""
    resolved_title = _clean_metadata_text(title)
    resolved_author = _clean_metadata_text(author)
    resolved_pubdate = _clean_metadata_text(pubdate)
    pubdate_timestamp = 0
    author_uid = 0
    description = ""
    aid = 0
    tid = 0

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
    if require_platform_metadata or not (
        resolved_title and resolved_author and resolved_pubdate
    ):
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
            author_uid = platform_metadata.author_uid
            description = platform_metadata.description
            aid = platform_metadata.aid
            tid = platform_metadata.tid

    if not (resolved_title or resolved_author or resolved_pubdate):
        return None

    return VideoMetadata(
        bvid=bvid,
        title=resolved_title,
        author=resolved_author,
        author_uid=author_uid,
        pubdate=resolved_pubdate,
        pubdate_timestamp=pubdate_timestamp,
        description=description,
        aid=aid,
        tid=tid,
    )


def _should_refresh_existing_summary_metadata(
    *,
    bvid: str,
    existing_results: Mapping[str, object],
) -> bool:
    """Return True when an old cached summary likely has Unknown metadata header."""
    if _xiaoyuzhou_episode_id(bvid) is None:
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
        kind = resolve_artifact_kind(artifact.kind, artifact.filename)
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


def _fetch_comments_for_existing_summary(
    *,
    bvid: str,
    metadata: VideoMetadata | None,
    work_dir: Path,
    storage_backend: StorageBackend,
    config: AppConfig,
    run_prefix: str,
    comment_limit: int | None,
    comment_status_callback: Callable[[str, int, int], None] | None = None,
) -> tuple[dict[str, StoredArtifact], str]:
    if metadata is None:
        if comment_status_callback is not None:
            comment_status_callback("unavailable", 0, 0)
        logger.warning("历史转录缺少平台元信息，已跳过评论下载")
        return {}, ""

    comment_platform = comment_platform_from_metadata(metadata)
    if comment_platform is None:
        if comment_status_callback is not None:
            comment_status_callback("unavailable", 0, 0)
        logger.warning("历史转录平台暂不支持评论下载，已跳过: %s", bvid)
        return {}, ""

    try:
        if comment_status_callback is not None:
            comment_status_callback("running", 0, 0)
        platform_label = comment_platform_label(comment_platform)
        logger.info(
            "历史评论补充配置：平台=%s，热门主评论=%s，子评论=每条主评论全部下载",
            platform_label,
            "全部" if comment_limit is None else f"{comment_limit} 条",
        )
        comments = fetch_platform_comments(
            platform=comment_platform,
            resource_id=metadata.bvid or bvid,
            aid=metadata.aid,
            up_uid=metadata.author_uid,
            limit=comment_limit,
            sort="hot",
            cookie=(
                build_bilibili_cookie(config)
                if comment_platform == Platform.BILIBILI
                else ""
            ),
        )
        comments_json_path = work_dir / f"{work_dir.name}_comments.json"
        comments_md_path = work_dir / f"{work_dir.name}_comments.md"
        write_comments_json(comments, comments_json_path)
        write_comments_markdown(comments, comments_md_path)
        comments_markdown_text = comments_md_path.read_text(encoding="utf-8")
        reply_count = count_comment_replies(comments)
        if comment_status_callback is not None:
            comment_status_callback("succeeded", comments.fetched_count, reply_count)
        logger.info(
            "历史评论补充完成：平台=%s，主评论=%s，子评论=%s，UP主回复=%s，排序=%s，来源=%s，资源=%s",
            platform_label,
            comments.fetched_count,
            reply_count,
            count_up_replies(comments),
            comments.sort,
            comments.source,
            metadata.bvid or bvid,
        )
        return {
            "comments_json": storage_backend.store_file(
                comments_json_path,
                object_key=f"{run_prefix}/{comments_json_path.name}",
            ),
            "comments_markdown": storage_backend.store_file(
                comments_md_path,
                object_key=f"{run_prefix}/{comments_md_path.name}",
            ),
        }, comments_markdown_text
    except Exception as exc:
        if comment_status_callback is not None:
            comment_status_callback("failed", 0, 0)
        logger.warning("历史转录评论补充失败，已跳过: %s", exc)
        return {}, ""


def _artifact_sibling_object_key(
    *,
    storage_backend: StorageBackend,
    config: AppConfig,
    source_storage_key: str,
    filename: str,
) -> str:
    parent_key = storage_parent_key(source_storage_key)
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
    fetch_stock_statuses: bool = False,
    refresh_stock_statuses: bool = False,
    stock_status_timeout_seconds: float | None = None,
    prefer_baostock_for_a_shares: bool = False,
    stock_status_max_workers: int = 1,
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
        summary_path = materialize_artifact(
            storage_backend,
            summary_artifact,
            work_dir,
        )
        summary_table_artifact = results.get("summary_table_md")
        table_md_path = (
            materialize_artifact(
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
                if fetch_stock_statuses or refresh_stock_statuses:
                    stock_statuses = get_or_fetch_stock_statuses(
                        db=get_history_db(),
                        bvid=bvid,
                        as_of_date=as_of_date,
                        markdown_paths=markdown_paths,
                        timeout_seconds=stock_status_timeout_seconds,
                        prefer_baostock_for_a_shares=prefer_baostock_for_a_shares,
                        max_workers=stock_status_max_workers,
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
        generated["summary_png"] = replace(
            _store_sibling_artifact(
                storage_backend=storage_backend,
                config=config,
                source_artifact=summary_artifact,
                path=summary_png_path,
            ),
            kind=ArtifactKind.SUMMARY_PNG,
            derived_from=summary_artifact.storage_key,
        )

        if include_no_table:
            no_table_md_path = summary_path.with_stem(f"{summary_path.stem}_no_table")
            MarkdownRemoveTableConverter().convert(summary_path, no_table_md_path)
            no_table_png_path = no_table_md_path.with_suffix(".png")
            png_converter.convert(no_table_md_path, no_table_png_path, is_table=False)
            generated["summary_no_table_png"] = replace(
                _store_sibling_artifact(
                    storage_backend=storage_backend,
                    config=config,
                    source_artifact=summary_artifact,
                    path=no_table_png_path,
                ),
                kind=ArtifactKind.SUMMARY_NO_TABLE_PNG,
                derived_from=summary_artifact.storage_key,
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
            generated["summary_table_png"] = replace(
                _store_sibling_artifact(
                    storage_backend=storage_backend,
                    config=config,
                    source_artifact=summary_table_artifact,
                    path=table_png_path,
                ),
                kind=ArtifactKind.SUMMARY_TABLE_PNG,
                derived_from=summary_table_artifact.storage_key,
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
    include_comments: bool = False,
    comment_limit: int | None = DEFAULT_COMMENT_LIMIT,
    metadata_callback: Callable[[VideoMetadata], None] | None = None,
    comment_status_callback: Callable[[str, int, int], None] | None = None,
    cancellation_token: CancellationToken | None = None,
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
        require_platform_metadata=include_comments,
    )
    if metadata is not None and metadata_callback is not None:
        metadata_callback(metadata)

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
        if cancellation_token is not None:
            cancellation_token.raise_if_cancelled()
        markdown_path = materialize_artifact(
            storage_backend,
            markdown_artifact,
            work_dir,
        )
        source_stem = markdown_path.stem
        if source_stem.lower().endswith("_transcription"):
            source_stem = source_stem[: -len("_transcription")]
        naming_source = (
            f"{metadata.title}{markdown_path.suffix}"
            if metadata is not None and metadata.title
            else f"{source_stem}{markdown_path.suffix}"
        )
        shortened_markdown_path = markdown_path.with_name(
            build_transcription_artifact_name(
                naming_source,
                transcription_id or bvid,
                preserve_extension=True,
            )
        )
        if shortened_markdown_path != markdown_path:
            markdown_path.replace(shortened_markdown_path)
            markdown_path = shortened_markdown_path

        comment_results: dict[str, StoredArtifact] = {}
        comments_markdown_text = ""
        if include_comments:
            if cancellation_token is not None:
                cancellation_token.raise_if_cancelled()
            comment_results, comments_markdown_text = (
                _fetch_comments_for_existing_summary(
                    bvid=bvid,
                    metadata=metadata,
                    work_dir=work_dir,
                    storage_backend=storage_backend,
                    config=config,
                    run_prefix=run_prefix,
                    comment_limit=comment_limit,
                    comment_status_callback=comment_status_callback,
                )
            )
            if cancellation_token is not None:
                cancellation_token.raise_if_cancelled()

        summary_path = summarize_with_comment_viewpoints(
            markdown_path,
            config.summarize,
            config.summary_presets,
            comments_markdown=comments_markdown_text,
            summary_context_config=config.summary_context,
            preset=summary_preset,
            profile=summary_profile,
            prompt_template_override=summary_prompt_template,
            metadata=metadata,
        )
        if cancellation_token is not None:
            cancellation_token.raise_if_cancelled()

        summary_table_md: Path | None = None
        try:
            summary_table_md = export_summary_table_without_video_time(summary_path)
        except Exception as exc:
            logger.warning("总结表格 Markdown 导出失败，已跳过: %s", exc)

        results: dict[str, object] = dict(comment_results)

        def _store(path: Path) -> StoredArtifact:
            def _store_path() -> StoredArtifact:
                return storage_backend.store_file(
                    path,
                    object_key=f"{run_prefix}/{path.name}",
                )

            if cancellation_token is not None:
                return cancellation_token.run_if_active(_store_path)
            return _store_path()

        try:
            if cancellation_token is not None:
                cancellation_token.raise_if_cancelled()
            results["summary"] = replace(
                _store(summary_path),
                kind=ArtifactKind.SUMMARY,
                derived_from=markdown_artifact.storage_key,
            )
            if summary_table_md is not None:
                results["summary_table_md"] = replace(
                    _store(summary_table_md),
                    kind=ArtifactKind.SUMMARY_TABLE_MD,
                    derived_from=results["summary"].storage_key,
                )
            summary_timeline = export_summary_timeline_text(summary_path)
            if summary_timeline is not None:
                results["summary_timeline"] = replace(
                    _store(summary_timeline),
                    kind=ArtifactKind.SUMMARY_TIMELINE,
                    derived_from=results["summary"].storage_key,
                )
            if cancellation_token is not None:
                cancellation_token.raise_if_cancelled()
        except PipelineCancelled:
            for artifact in results.values():
                if not isinstance(artifact, StoredArtifact):
                    continue
                try:
                    storage_backend.delete_file(artifact.storage_key)
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "清理已取消的总结产物失败: %s: %s",
                        artifact.storage_key,
                        exc,
                    )
            raise

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
    if resolve_artifact_kind(summary_artifact.kind, summary_artifact.filename) not in (
        ArtifactKind.SUMMARY,
        ArtifactKind.RAG_ANSWER,
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
        summary_path = materialize_artifact(
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
        return replace(
            stored,
            kind=ArtifactKind.SUMMARY_FANCY_HTML,
            derived_from=summary_artifact.storage_key,
            summary_preset=summary_artifact.summary_preset,
            summary_profile=summary_artifact.summary_profile,
        )
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
                    kind=resolve_artifact_kind(artifact.kind, artifact.filename),
                    filename=artifact.filename,
                    storage_key=artifact.storage_key,
                    backend=artifact.backend,
                    derived_from=artifact.derived_from,
                    summary_preset=(summary_preset or artifact.summary_preset).strip(),
                    summary_profile=(
                        summary_profile or artifact.summary_profile
                    ).strip(),
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
                kind=resolve_artifact_kind(artifact.kind, artifact.filename),
                filename=artifact.filename,
                storage_key=artifact.storage_key,
                backend=artifact.backend,
                derived_from=artifact.derived_from,
                summary_preset=(summary_preset or artifact.summary_preset).strip(),
                summary_profile=(summary_profile or artifact.summary_profile).strip(),
            )
        )
    has_summary = any(item.kind in SUMMARY_ARTIFACT_KINDS for item in merged_artifacts)
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
        "kind": resolve_artifact_kind(artifact.kind, artifact.filename),
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
        title = metadata.title if metadata else ""
        tid = metadata.tid if metadata else 0
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
            title=title,
            author=author,
            pubdate=pubdate,
            tid=tid,
            created_at=created_at,
            summary_preset=resolved_preset,
            summary_profile=resolved_profile,
            merge_existing_artifacts=True,
        )
    except Exception as exc:
        logger.warning("记录历史转录失败: %s", exc)
        return None
