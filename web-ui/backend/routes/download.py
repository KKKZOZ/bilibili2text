"""Download and convert endpoints."""

import tempfile
from pathlib import Path
from urllib.parse import quote
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from b2t.converter.converter import ConversionFormat, convert_file
from b2t.storage import StoredArtifact
from b2t.storage.base import classify_artifact_filename

from backend.download_registry import download_registry, media_type_for_filename
from backend.schemas import ConvertRequest, ConvertResponse
from backend.dependencies import get_history_db, get_storage_backend

router = APIRouter()


def _sibling_storage_key(source_storage_key: str, filename: str) -> str:
    normalized = source_storage_key.replace("\\", "/")
    if "/" not in normalized:
        return filename
    return f"{normalized.rsplit('/', 1)[0]}/{filename}"


def _precomputed_convert_filename(
    filename: str,
    source_kind: str,
    target_format: ConversionFormat,
    source_variant: str | None,
) -> str:
    path = Path(filename)
    if target_format == ConversionFormat.PNG:
        if source_kind == "summary":
            if source_variant == "summary_no_table":
                return f"{path.stem}_no_table.png"
            return f"{path.stem}.png"
        if source_kind == "summary_table_md":
            return f"{path.stem}.png"
    if target_format == ConversionFormat.MD_NO_TABLE and source_kind == "summary":
        return f"{path.stem}_no_table.md"
    return ""


def _find_precomputed_conversion(
    *,
    artifact: StoredArtifact,
    target_format: ConversionFormat,
    source_variant: str | None,
) -> StoredArtifact | None:
    source_kind = classify_artifact_filename(artifact.filename) or ""
    filename = _precomputed_convert_filename(
        artifact.filename,
        source_kind,
        target_format,
        source_variant,
    )
    if not filename or filename == artifact.filename:
        return None

    candidate = StoredArtifact(
        filename=filename,
        storage_key=_sibling_storage_key(artifact.storage_key, filename),
        backend=artifact.backend,
    )
    storage_backend = get_storage_backend()
    try:
        with storage_backend.open_stream(candidate.storage_key):
            pass
    except FileNotFoundError:
        return None
    return candidate


def _convert_response_for_artifact(artifact: StoredArtifact) -> ConvertResponse:
    download_id = download_registry.store_artifact(artifact)
    return ConvertResponse(
        download_url=f"/api/download/{download_id}",
        filename=artifact.filename,
    )


def _lookup_artifact_pubdate(storage_key: str) -> str:
    try:
        db = get_history_db()
        with db._connect() as conn:
            row = conn.execute(
                """
                SELECT r.pubdate
                FROM transcription_artifacts a
                JOIN transcription_runs r ON r.run_id = a.run_id
                WHERE a.storage_key = ?
                LIMIT 1
                """,
                (storage_key,),
            ).fetchone()
    except Exception:
        return ""
    if row is None:
        return ""
    return str(row["pubdate"] or "").strip()


@router.get("/api/download/{download_id}")
def download_markdown(download_id: str) -> StreamingResponse:
    # Check in-memory content cache first (e.g. RAG answers)
    cached = download_registry.get_content(download_id)
    if cached is not None:
        content, filename = cached
        quoted_filename = quote(filename)
        return StreamingResponse(
            iter([content]),
            media_type=media_type_for_filename(filename),
            headers={
                "Content-Disposition": f"attachment; filename*=UTF-8''{quoted_filename}"
            },
        )

    artifact = download_registry.get_artifact(download_id)

    if artifact is None:
        raise HTTPException(status_code=404, detail="下载链接不存在或已过期")

    storage_backend = get_storage_backend()
    stream_cm = storage_backend.open_stream(artifact.storage_key)
    try:
        stream = stream_cm.__enter__()
    except FileNotFoundError:
        raise HTTPException(status_code=410, detail="文件不存在，请重新生成") from None
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"读取存储文件失败: {exc}",
        ) from exc

    def iter_stream():
        try:
            while True:
                chunk = stream.read(1024 * 1024)
                if not chunk:
                    break
                yield chunk
        finally:
            stream_cm.__exit__(None, None, None)

    quoted_filename = quote(artifact.filename)
    return StreamingResponse(
        iter_stream(),
        media_type=media_type_for_filename(artifact.filename),
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quoted_filename}"
        },
    )


@router.post("/api/convert", response_model=ConvertResponse)
def convert_artifact(payload: ConvertRequest) -> ConvertResponse:
    """
    Convert file format online.

    Supported conversions:
    - Markdown -> txt, pdf, png, html
    - HTML (fancy) -> png
    """
    artifact = download_registry.get_artifact(payload.download_id)

    if artifact is None:
        raise HTTPException(status_code=404, detail="下载链接不存在或已过期")

    # Validate target format
    try:
        target_format = ConversionFormat(payload.target_format.lower())
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的目标格式: {payload.target_format}",
        ) from None

    # Check source file format
    source_suffix = Path(artifact.filename).suffix.lower().lstrip(".")
    _md_suffixes = ("md", "markdown")
    _html_suffixes = ("html", "htm")
    if source_suffix in _html_suffixes and target_format != ConversionFormat.PNG:
        raise HTTPException(
            status_code=400,
            detail="HTML 文件仅支持转换为 PNG",
        )
    if source_suffix not in (*_md_suffixes, *_html_suffixes):
        raise HTTPException(
            status_code=400,
            detail=f"不支持转换此文件类型: {source_suffix}",
        )

    storage_backend = get_storage_backend()
    precomputed = _find_precomputed_conversion(
        artifact=artifact,
        target_format=target_format,
        source_variant=payload.source_variant,
    )
    if precomputed is not None:
        return _convert_response_for_artifact(precomputed)

    # Download source file to temporary directory
    with tempfile.TemporaryDirectory(prefix="b2t-convert-") as temp_dir:
        temp_dir_path = Path(temp_dir)
        source_path = temp_dir_path / artifact.filename

        try:
            with storage_backend.open_stream(artifact.storage_key) as stream:
                with source_path.open("wb") as output:
                    while True:
                        chunk = stream.read(1024 * 1024)
                        if not chunk:
                            break
                        output.write(chunk)
        except FileNotFoundError:
            raise HTTPException(
                status_code=410,
                detail="源文件不存在，请重新生成",
            ) from None
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail=f"读取源文件失败: {exc}",
            ) from exc

        # Execute conversion
        try:
            source_kind = classify_artifact_filename(artifact.filename) or ""
            png_is_table = (
                target_format == ConversionFormat.PNG
                and source_kind == "summary_table_md"
            )
            pdf_is_table = (
                target_format == ConversionFormat.PDF
                and source_kind == "summary_table_md"
            )
            convert_options = {}
            if target_format == ConversionFormat.PNG and source_kind == "summary":
                convert_options["dpr"] = 4
            if target_format == ConversionFormat.PDF and source_kind == "summary":
                convert_options["enhance_stock_tables"] = True
            if png_is_table or pdf_is_table:
                pubdate = _lookup_artifact_pubdate(artifact.storage_key)
                if pubdate:
                    convert_options["as_of_date"] = pubdate
            explicit_output_path = None
            if (
                source_suffix in _html_suffixes
                and target_format == ConversionFormat.PNG
            ):
                render_mode = payload.render_mode or "desktop"
                if render_mode == "mobile":
                    convert_options.update(
                        width=430,
                        height=932,
                        dpr=3,
                        is_mobile=True,
                    )
                    explicit_output_path = source_path.with_name(
                        f"{source_path.stem}_mobile.png"
                    )
                else:
                    convert_options.update(
                        width=1440,
                        height=1080,
                        dpr=2,
                        is_mobile=False,
                    )
                    explicit_output_path = source_path.with_name(
                        f"{source_path.stem}_desktop.png"
                    )
            output_path = convert_file(
                source_path,
                target_format,
                output_path=explicit_output_path,
                is_table=(png_is_table or pdf_is_table),
                **convert_options,
            )
        except RuntimeError as exc:
            raise HTTPException(
                status_code=500,
                detail=str(exc),
            ) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail=f"转换失败: {exc}",
            ) from exc

        # Store the converted file
        converted_filename = output_path.name
        try:
            converted_artifact = storage_backend.store_file(
                output_path,
                object_key=f"converted/{uuid4().hex}/{converted_filename}",
            )
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail=f"保存转换结果失败: {exc}",
            ) from exc

    # Register download
    download_id = download_registry.store_artifact(converted_artifact)

    return ConvertResponse(
        download_url=f"/api/download/{download_id}",
        filename=converted_filename,
    )
