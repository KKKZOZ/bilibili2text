"""Bridge b2t stored sources to Pi without repeating download or transcription."""

import shutil
import tempfile
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from b2t.download.platform import build_filename_component
from b2t.report.generate import generate_report
from b2t.report.options import ReportOptions
from b2t.storage import ArtifactKind, StoredArtifact
from backend.artifacts import materialize_artifact


def generate_stored_report(
    *,
    source_artifact,
    storage_backend,
    config,
    options=None,
    metadata=None,
    json_artifact=None,
    cancellation_token=None,
    progress_callback=None,
):
    from backend.services import _artifact_sibling_object_key

    options = options or ReportOptions()
    with tempfile.TemporaryDirectory(prefix="b2t-report-source-") as temporary:
        work = Path(temporary)
        source = materialize_artifact(storage_backend, source_artifact, work)
        json_path = (
            materialize_artifact(storage_backend, json_artifact, work)
            if json_artifact
            else None
        )
        report = generate_report(
            source,
            config,
            options=options,
            metadata=metadata,
            json_path=json_path,
            cancellation_token=cancellation_token,
            progress_callback=progress_callback,
        )
        if progress_callback:
            progress_callback("报告校验通过，正在保存文件")
        # Each generation is a distinct artifact, including reruns with the same mode.
        filename = build_filename_component(
            source.stem, suffix=f"_{options.mode}_{uuid4().hex[:8]}_summary_fancy.html"
        )
        key = _artifact_sibling_object_key(
            storage_backend=storage_backend,
            config=config,
            source_storage_key=source_artifact.storage_key,
            filename=filename,
        )
        if cancellation_token:
            cancellation_token.raise_if_cancelled()
        if storage_backend.persist_local_outputs:
            destination = Path(source_artifact.storage_key).parent / filename
            shutil.copyfile(report, destination)
        else:
            destination = report.with_name(filename)
            report.rename(destination)
        stored = storage_backend.store_file(destination, object_key=key)
        return replace(
            stored,
            kind=ArtifactKind.SUMMARY_FANCY_HTML,
            derived_from=source_artifact.storage_key,
            summary_profile=options.profile or config.fancy_html.profile,
        )


def transcript_for_summary(summary: StoredArtifact) -> StoredArtifact:
    if not summary.derived_from:
        raise ValueError("旧总结缺少原文关联，请在新建转录页面提交原链接并开启阅读报告")
    return StoredArtifact(
        filename=Path(summary.derived_from).name,
        storage_key=summary.derived_from,
        backend=summary.backend,
        kind=ArtifactKind.MARKDOWN,
    )
