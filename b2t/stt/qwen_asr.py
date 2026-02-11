"""Qwen3-ASR-Flash 语音转文字"""

import logging
from pathlib import Path

import dashscope
import requests
from dashscope.audio.qwen_asr import QwenTranscription

from b2t.config import STTConfig

logger = logging.getLogger(__name__)


def transcribe(audio_url: str, config: STTConfig):
    """使用 Qwen3-ASR-Flash-Filetrans 转录音频

    Args:
        audio_url: 音频文件的公共 URL
        config: STT 配置

    Returns:
        DashScope 转录任务结果

    Raises:
        Exception: 转录失败时抛出
    """
    logger.info("开始转录音频: %s", audio_url)

    dashscope.base_http_api_url = config.base_url
    dashscope.api_key = config.api_key

    task_response = QwenTranscription.async_call(
        model=config.model,
        file_url=audio_url,
        language=config.language,
        enable_itn=True,
        enable_words=True,
    )

    logger.info("任务已提交，task_id: %s", task_response.output.task_id)
    logger.info("等待转录完成...")

    task_result = QwenTranscription.wait(task=task_response.output.task_id)

    return task_result


def download_result(url: str, output_path: Path | str) -> Path:
    """下载转录结果 JSON 文件

    Args:
        url: 转录结果 URL
        output_path: 保存路径

    Returns:
        保存的文件路径
    """
    output_path = Path(output_path)
    logger.info("下载转录结果到: %s", output_path)

    response = requests.get(url)
    response.raise_for_status()

    output_path.write_text(response.text, encoding="utf-8")

    logger.info("转录结果已保存到: %s", output_path)
    return output_path
