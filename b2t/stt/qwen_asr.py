"""Qwen3-ASR-Flash 语音转文字"""

import logging
import time
from pathlib import Path

import dashscope
import requests
from dashscope.audio.qwen_asr import QwenTranscription

from b2t.config import STTConfig
from b2t.storage.base import StorageBackend
from b2t.stt.base import ProgressCallback, STTProvider

logger = logging.getLogger(__name__)


class QwenSTTProvider(STTProvider):
    """Qwen STT Provider（内部处理存储上传与结果下载）。"""

    def __init__(self, stt_config: STTConfig, storage_backend: StorageBackend) -> None:
        self._stt_config = stt_config
        self._storage_backend = storage_backend

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
        if not self._storage_backend.supports_public_url():
            raise ValueError(
                "当前 STT 上传存储不支持公网 URL，无法用于 qwen 转录。"
                "请将当前 stt.profile 对应的 storage_profile（或 storage.backend）设置为 minio 或 alicloud。"
            )

        file_size_mb = audio_path.stat().st_size / 1024 / 1024
        logger.info("正在上传音频至存储后端: %s (%.1f MB)", audio_path.name, file_size_mb)
        t0 = time.perf_counter()
        with self._storage_backend.temporary_public_url(audio_path) as audio_url:
            upload_elapsed = time.perf_counter() - t0
            logger.info("音频已上传，耗时 %.1f 秒，正在提交 Dashscope 转录任务", upload_elapsed)
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

        logger.info("正在调用 Dashscope API: %s", self._stt_config.qwen_base_url)
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
