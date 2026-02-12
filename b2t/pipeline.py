"""主流程编排"""

import logging
import shutil
from pathlib import Path
from typing import Callable

from b2t.config import AppConfig
from b2t.converter.json_to_md import convert_json_to_md
from b2t.converter.md_to_txt import convert_md_to_txt
from b2t.download.yutto import download_audio
from b2t.summarize.llm import export_summary_table_pdf, summarize
from b2t.stt import create_stt_provider

logger = logging.getLogger(__name__)


def run_pipeline(
    url: str,
    config: AppConfig,
    *,
    skip_summary: bool = False,
    summary_preset: str | None = None,
    summary_profile: str | None = None,
    output_dir: Path | str | None = None,
    progress_callback: Callable[[str, str, int], None] | None = None,
) -> dict[str, Path]:
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
        包含各阶段输出文件路径的字典：
        - "audio": 音频文件路径
        - "json": 转录 JSON 路径
        - "markdown": Markdown 路径
        - "text": 原文 TXT 路径
        - "summary": 总结文件路径（跳过总结时不包含）
        - "summary_text": 总结 TXT 路径（跳过总结时不包含）
        - "summary_table_pdf": 总结表格 PDF 路径（存在表格时包含）
    """
    results: dict[str, Path] = {}

    transcribe_root = Path(output_dir or config.download.output_dir)
    transcribe_root.mkdir(parents=True, exist_ok=True)

    temp_download_dir = transcribe_root / "temp_download"
    temp_download_dir.mkdir(exist_ok=True)

    def emit_progress(stage: str, label: str, progress: int) -> None:
        if progress_callback is not None:
            progress_callback(stage, label, progress)

    try:
        # 1. 下载音频
        emit_progress("downloading", "下载视频音频", 10)
        logger.info("=== 下载音频 ===")
        audio_file = download_audio(
            url, temp_download_dir, config.download.audio_quality
        )

        # 创建专属工作目录
        work_dir = transcribe_root / audio_file.stem
        work_dir.mkdir(exist_ok=True)

        # 移动音频到工作目录
        new_audio_path = work_dir / audio_file.name
        shutil.move(str(audio_file), new_audio_path)
        results["audio"] = new_audio_path
        logger.info("工作目录: %s", work_dir)

        # 2. 转录（provider 内部处理各自细节，例如 Qwen 的 OSS 上传）
        stt_provider = create_stt_provider(config)
        json_path = stt_provider.transcribe(
            new_audio_path,
            work_dir,
            progress_callback=emit_progress,
        )
        results["json"] = json_path

        # 3. JSON → Markdown
        emit_progress("converting", "生成 Markdown", 80)
        logger.info("=== 生成 Markdown 文件 ===")
        md_path = convert_json_to_md(json_path, min_length=config.converter.min_length)
        results["markdown"] = md_path
        results["text"] = convert_md_to_txt(md_path)

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
            results["summary"] = summary_path
            results["summary_text"] = convert_md_to_txt(summary_path)
            try:
                summary_table_pdf = export_summary_table_pdf(summary_path)
            except Exception as exc:
                logger.warning("总结表格 PDF 导出失败，已跳过: %s", exc)
            else:
                if summary_table_pdf is not None:
                    results["summary_table_pdf"] = summary_table_pdf

        emit_progress("completed", "处理完成", 100)
        logger.info("所有文件已保存到: %s", work_dir)

    finally:
        # 清理临时下载目录
        if temp_download_dir.exists():
            shutil.rmtree(temp_download_dir)

    return results
