"""Download and convert endpoints."""

import tempfile
from pathlib import Path
from urllib.parse import quote
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from b2t.converter.converter import ConversionFormat, convert_file
from b2t.storage.base import classify_artifact_filename

from backend.downloads import (
    _content_cache,
    _content_cache_lock,
    _media_type_for_filename,
    _store_download,
)
from backend.schemas import ConvertRequest, ConvertResponse
from backend.state import _download_index, _download_lock, _get_storage_backend

router = APIRouter()


@router.get("/api/download/{download_id}")
def download_markdown(download_id: str) -> StreamingResponse:
    # Check in-memory content cache first (e.g. RAG answers)
    with _content_cache_lock:
        cached = _content_cache.get(download_id)
    if cached is not None:
        content, filename = cached
        quoted_filename = quote(filename)
        return StreamingResponse(
            iter([content]),
            media_type=_media_type_for_filename(filename),
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quoted_filename}"},
        )

    with _download_lock:
        artifact = _download_index.get(download_id)

    if artifact is None:
        raise HTTPException(status_code=404, detail="下载链接不存在或已过期")

    storage_backend = _get_storage_backend()
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
        media_type=_media_type_for_filename(artifact.filename),
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quoted_filename}"
        },
    )


@router.post("/api/convert", response_model=ConvertResponse)
def convert_artifact(payload: ConvertRequest) -> ConvertResponse:
    """
    在线转换文件格式。

    支持的转换：
    - Markdown -> txt, pdf, png, html
    - HTML (fancy) -> png
    """
    with _download_lock:
        artifact = _download_index.get(payload.download_id)

    if artifact is None:
        raise HTTPException(status_code=404, detail="下载链接不存在或已过期")

    # 验证目标格式
    try:
        target_format = ConversionFormat(payload.target_format.lower())
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的目标格式: {payload.target_format}",
        ) from None

    # 检查源文件格式
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

    storage_backend = _get_storage_backend()

    # 下载源文件到临时目录
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

        # 执行转换
        try:
            source_kind = classify_artifact_filename(artifact.filename) or ""
            png_is_table = (
                target_format == ConversionFormat.PNG
                and source_kind == "summary_table_md"
            )
            convert_options = {}
            explicit_output_path = None
            if source_suffix in _html_suffixes and target_format == ConversionFormat.PNG:
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
                is_table=png_is_table,
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

        # 存储转换后的文件
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

    # 注册下载
    download_id = _store_download(converted_artifact)

    return ConvertResponse(
        download_url=f"/api/download/{download_id}",
        filename=converted_filename,
    )
