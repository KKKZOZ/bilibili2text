"""Qwen3-ASR-Flash 语音转文字"""

import logging
from pathlib import Path

import dashscope
import requests
from dashscope.audio.qwen_asr import QwenTranscription

from b2t.config import OSSConfig, STTConfig
from b2t.oss.client import OSSManager
from b2t.stt.base import ProgressCallback, STTProvider

logger = logging.getLogger(__name__)


class QwenSTTProvider(STTProvider):
    """Qwen STT Provider（内部处理 OSS 上传与结果下载）。"""

    def __init__(self, stt_config: STTConfig, oss_config: OSSConfig) -> None:
        self._stt_config = stt_config
        self._oss_config = oss_config

    def transcribe(
        self,
        audio_path: Path,
        work_dir: Path,
        progress_callback: ProgressCallback | None = None,
    ) -> Path:
        def emit(stage: str, label: str, progress: int) -> None:
            if progress_callback is not None:
                progress_callback(stage, label, progress)

        json_path = work_dir / f"{audio_path.stem}_transcription.json"

        emit("transcribing", "语音转录", 35)
        oss_manager = OSSManager(self._oss_config)

        with oss_manager.temporary_upload(audio_path) as audio_url:
            emit("transcribing", "语音转录", 50)
            response = self._submit_task(audio_url)

            if response.output.task_status != "SUCCEEDED":
                raise RuntimeError(f"转录失败，状态: {response.output.task_status}")

            emit("transcribing", "语音转录", 65)
            transcription_url = response.output.result["transcription_url"]
            self._download_result(transcription_url, json_path)

        return json_path

    def _submit_task(self, audio_url: str):
        """提交 Qwen 转录任务并等待完成。"""
        logger.info("开始转录音频: [REDACTED_URL]")

        if not self._stt_config.qwen_api_key:
            raise ValueError("缺少 stt.qwen_api_key 配置")

        dashscope.base_http_api_url = self._stt_config.qwen_base_url
        dashscope.api_key = self._stt_config.qwen_api_key

        task_response = QwenTranscription.async_call(
            model=self._stt_config.qwen_model,
            file_url=audio_url,
            language=self._stt_config.language,
            enable_itn=True,
            enable_words=True,
        )

        logger.info("任务已提交，task_id: %s", task_response.output.task_id)
        logger.info("等待转录完成...")

        return QwenTranscription.wait(task=task_response.output.task_id)

    def _download_result(self, url: str, output_path: Path | str) -> Path:
        """下载转录结果 JSON 文件。"""
        output_path = Path(output_path)
        logger.info("下载转录结果到: %s", output_path)

        response = requests.get(url)
        response.raise_for_status()
        output_path.write_text(response.text, encoding="utf-8")

        logger.info("转录结果已保存到: %s", output_path)
        return output_path
