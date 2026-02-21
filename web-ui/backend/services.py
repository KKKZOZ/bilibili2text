"""Business logic helpers: artifact building, summary execution, and history recording."""

import logging
import tempfile
from pathlib import Path
from typing import Mapping
from uuid import uuid4

from b2t.config import AppConfig
from b2t.converter.md_to_txt import convert_md_to_txt
from b2t.history import record_pipeline_run
from b2t.storage import StorageBackend, StoredArtifact
from b2t.storage.base import classify_artifact_filename
from b2t.summarize.llm import (
    export_summary_table_markdown,
    export_summary_table_pdf,
    summarize,
)

from backend.downloads import _store_download
from backend.state import _get_history_db

logger = logging.getLogger(__name__)


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
