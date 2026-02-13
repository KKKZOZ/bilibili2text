"""主流程编排"""

import logging
import shutil
from pathlib import Path
import tempfile
from typing import Callable
from uuid import uuid4

from b2t.config import AppConfig
from b2t.converter.json_to_md import convert_json_to_md
from b2t.download.yutto_cli import extract_bvid
from b2t.download.yutto import download_audio
from b2t.storage import (
    StoredArtifact,
    create_storage_backend,
    create_stt_storage_backend,
)
from b2t.summarize.llm import extract_markdown_table_block, summarize
from b2t.stt import create_stt_provider

logger = logging.getLogger(__name__)


def _extract_summary_table(summary_path: Path) -> Path | None:
    """从总结 Markdown 中提取最后一个表格，保存为单独的文件。

    Args:
        summary_path: 总结 Markdown 文件路径

    Returns:
        表格文件路径，如果没有表格则返回 None
    """
    content = summary_path.read_text(encoding="utf-8")
    table_content = extract_markdown_table_block(content, which="last")
    if table_content is None:
        logger.info("总结中没有找到表格")
        return None

    # 保存表格文件
    table_path = summary_path.with_stem(f"{summary_path.stem}_table")
    table_path.write_text(table_content, encoding="utf-8")
    logger.info("已提取表格到: %s", table_path)
    return table_path


def _ensure_bvid_prefixed_name(name: str, bvid: str) -> str:
    lowered = name.lower()
    bvid_lower = bvid.lower()
    if lowered.startswith(bvid_lower):
        return name
    return f"{bvid}_{name}"


def run_pipeline(
    url: str,
    config: AppConfig,
    *,
    skip_summary: bool = False,
    summary_preset: str | None = None,
    summary_profile: str | None = None,
    output_dir: Path | str | None = None,
    progress_callback: Callable[[str, str, int], None] | None = None,
) -> dict[str, StoredArtifact]:
    """执行完整的转录流程

    流程：下载音频文件 → 转录 → 总结

    Args:
        url: Bilibili 视频 URL
        config: 应用配置
        skip_summary: 是否跳过 LLM 总结
        summary_preset: 总结 preset 名称，为 None 时使用配置默认值
        summary_profile: 总结模型 profile 名称，为 None 时使用配置默认值
        output_dir: 输出根目录，为 None 时使用配置中的 download.output_dir
        progress_callback: 阶段进度回调，参数为 (stage_key, stage_label, progress_percent)

    Returns:
        包含各阶段输出文件的存储信息：
        - "audio": 音频文件
        - "json": 转录 JSON
        - "markdown": 原文 Markdown
        - "summary": 总结 Markdown（跳过总结时不包含）
        - "summary_table_md": 总结表格 Markdown（存在表格时包含）
    """
    results: dict[str, StoredArtifact] = {}
    local_results: dict[str, Path] = {}
    storage_backend = create_storage_backend(config)
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
        # 1. 下载音频并获取元信息
        emit_progress("downloading", "下载视频音频", 10)
        logger.info("=== 下载音频 ===")
        audio_file, metadata = download_audio(
            url, temp_download_dir, config.download.audio_quality
        )
        bvid = extract_bvid(url) or extract_bvid(audio_file.name)
        if bvid is None:
            raise ValueError(
                "无法从输入链接中提取 BV 号，无法按 BV 前缀命名输出文件"
            )

        # 记录元信息
        if metadata:
            logger.info("视频作者: %s, 发布时间: %s", metadata.author, metadata.pubdate)
            results["_metadata"] = metadata  # 临时存储元信息，供后续使用

        # 创建专属工作目录
        work_dir = transcribe_root / _ensure_bvid_prefixed_name(audio_file.stem, bvid)
        work_dir.mkdir(exist_ok=True)

        # 移动音频到工作目录
        audio_filename = _ensure_bvid_prefixed_name(audio_file.name, bvid)
        new_audio_path = work_dir / audio_filename
        shutil.move(str(audio_file), new_audio_path)
        local_results["audio"] = new_audio_path
        logger.info("工作目录: %s", work_dir)

        # 2. 转录（provider 内部处理各自细节，例如 Qwen 的 OSS 上传）
        stt_provider = create_stt_provider(config, stt_storage_backend)
        json_path = stt_provider.transcribe(
            new_audio_path,
            work_dir,
            progress_callback=emit_progress,
        )
        local_results["json"] = json_path

        # 3. JSON → Markdown
        emit_progress("converting", "生成 Markdown", 80)
        logger.info("=== 生成 Markdown 文件 ===")
        md_path = convert_json_to_md(json_path, min_length=config.converter.min_length)
        local_results["markdown"] = md_path

        # 4. LLM 总结
        if not skip_summary:
            emit_progress("summarizing", "LLM 整理总结", 90)
            logger.info("=== 生成总结 ===")
            summary_path = summarize(
                md_path,
                config.summarize,
                config.summary_presets,
                preset=summary_preset,
                profile=summary_profile,
            )
            local_results["summary"] = summary_path

            # 提取总结中的表格为单独的 Markdown 文件
            summary_table_md_path = _extract_summary_table(summary_path)
            if summary_table_md_path is not None:
                local_results["summary_table_md"] = summary_table_md_path

        storage_prefix = f"{bvid}-{uuid4().hex[:8]}"
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
        # 清理临时下载目录
        if temp_download_dir.exists():
            shutil.rmtree(temp_download_dir)
        # MinIO backend 下使用临时目录，流程结束后清理全部本地文件
        if not storage_backend.persist_local_outputs and transcribe_root.exists():
            shutil.rmtree(transcribe_root, ignore_errors=True)

    return results
