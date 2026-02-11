"""主流程编排"""

import logging
import shutil
from pathlib import Path

from b2t.config import AppConfig
from b2t.converter.json_to_md import convert_json_to_md
from b2t.download.yutto import download_audio
from b2t.oss.client import OSSManager
from b2t.polish.llm import summarize
from b2t.stt.qwen_asr import download_result, transcribe

logger = logging.getLogger(__name__)


def run_pipeline(
    url: str,
    config: AppConfig,
    *,
    skip_summary: bool = False,
    output_dir: Path | str | None = None,
) -> dict[str, Path]:
    """执行完整的转录流程

    流程：下载 → OSS 上传 → 转录 → 下载结果 → 转 MD → 总结

    Args:
        url: Bilibili 视频 URL
        config: 应用配置
        skip_summary: 是否跳过 LLM 总结
        output_dir: 输出根目录，为 None 时使用配置中的 download.output_dir

    Returns:
        包含各阶段输出文件路径的字典：
        - "audio": 音频文件路径
        - "json": 转录 JSON 路径
        - "markdown": Markdown 路径
        - "summary": 总结文件路径（跳过总结时不包含）
    """
    results: dict[str, Path] = {}

    transcribe_root = Path(output_dir or config.download.output_dir)
    transcribe_root.mkdir(parents=True, exist_ok=True)

    temp_download_dir = transcribe_root / "temp_download"
    temp_download_dir.mkdir(exist_ok=True)

    oss_manager = OSSManager(config.oss)

    try:
        # 1. 下载音频
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

        # 2. 上传到 OSS 并转录
        with oss_manager.temporary_upload(new_audio_path) as audio_url:
            # 3. 转录
            logger.info("=== 开始转录 ===")
            response = transcribe(audio_url, config.stt)

            logger.info("=== 转录结果 ===")
            logger.debug("%s", response)

            if response.output.task_status != "SUCCEEDED":
                raise RuntimeError(
                    f"转录失败，状态: {response.output.task_status}"
                )

            # 4. 下载转录结果
            transcription_url = response.output.result["transcription_url"]
            json_path = work_dir / f"{new_audio_path.stem}_transcription.json"
            download_result(transcription_url, json_path)
            results["json"] = json_path

        # 5. JSON → Markdown
        logger.info("=== 生成 Markdown 文件 ===")
        md_path = convert_json_to_md(json_path, min_length=config.converter.min_length)
        results["markdown"] = md_path

        # 6. LLM 总结
        if not skip_summary:
            logger.info("=== 生成总结 ===")
            summary_path = summarize(md_path, config.polish)
            results["summary"] = summary_path

        logger.info("所有文件已保存到: %s", work_dir)

    finally:
        # 清理临时下载目录
        if temp_download_dir.exists():
            shutil.rmtree(temp_download_dir)

    return results
