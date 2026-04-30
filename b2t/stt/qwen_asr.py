"""DashScope speech-to-text (Qwen/FileTrans and FunASR)"""

import logging
import time
from pathlib import Path
from typing import Any

import dashscope
import requests
from dashscope.audio.asr import Transcription
from dashscope.audio.qwen_asr import QwenTranscription

from b2t.config import STTConfig
from b2t.storage.base import StorageBackend
from b2t.stt.base import ProgressCallback, STTProvider

logger = logging.getLogger(__name__)


def _is_fun_asr_model(model: str) -> bool:
    return model.strip().lower() == "fun-asr"


def _safe_get(data: Any, key: str) -> Any:
    if isinstance(data, dict):
        return data.get(key)
    return data.__dict__.get(key) if hasattr(data, "__dict__") else None


class QwenSTTProvider(STTProvider):
    """Qwen STT Provider (handles storage upload and result download internally)."""

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

        emit("transcribing", "Speech transcription", 35)
        if not self._storage_backend.supports_public_url():
            raise ValueError(
                "The current STT storage backend does not support public URLs and cannot be used for qwen transcription. "
                "Please set the storage_profile for the current stt.profile (or storage.backend) to minio or alicloud."
            )

        file_size_mb = audio_path.stat().st_size / 1024 / 1024
        logger.info("Uploading audio to storage backend: %s (%.1f MB)", audio_path.name, file_size_mb)
        t0 = time.perf_counter()
        with self._storage_backend.temporary_public_url(audio_path) as audio_url:
            upload_elapsed = time.perf_counter() - t0
            logger.info("Audio uploaded in %.1f seconds, submitting Dashscope transcription task", upload_elapsed)
            emit("transcribing", "Speech transcription", 50)
            response = self._submit_task(audio_url)

            task_status = self._extract_task_status(response)
            if task_status != "SUCCEEDED":
                raise RuntimeError(f"转录失败，状态: {task_status}")

            emit("transcribing", "Speech transcription", 65)
            transcription_url = self._extract_transcription_url(response)
            self._download_result(transcription_url, json_path)

        return json_path

    def _submit_task(self, audio_url: str):
        """Submit Qwen transcription task and wait for completion."""
        logger.info("开始转录音频: [REDACTED_URL]")

        if not self._stt_config.qwen_api_key:
            raise ValueError("Missing stt.qwen_api_key config")

        dashscope.base_http_api_url = self._stt_config.qwen_base_url
        dashscope.api_key = self._stt_config.qwen_api_key

        logger.info("Calling Dashscope API: %s", self._stt_config.qwen_base_url)
        model = self._stt_config.qwen_model.strip()
        if _is_fun_asr_model(model):
            task_response = Transcription.async_call(
                model=model,
                file_urls=[audio_url],
                language_hints=[self._stt_config.language],
            )
            wait_fn = Transcription.wait
        else:
            task_response = QwenTranscription.async_call(
                model=model,
                file_url=audio_url,
                language=self._stt_config.language,
                enable_itn=True,
                enable_words=True,
            )
            wait_fn = QwenTranscription.wait

        logger.info("Task submitted, task_id: %s", task_response.output.task_id)
        logger.info("Waiting for transcription to complete...")

        return wait_fn(task=task_response.output.task_id)

    def _extract_task_status(self, response: Any) -> str:
        output = response.output

        task_status = _safe_get(output, "task_status")
        if isinstance(task_status, str) and task_status:
            return task_status

        if isinstance(output, dict):
            results = output.get("results")
            if isinstance(results, list) and results:
                first = results[0]
                if isinstance(first, dict):
                    subtask_status = first.get("subtask_status")
                    if isinstance(subtask_status, str) and subtask_status:
                        return subtask_status

        return ""

    def _extract_transcription_url(self, response: Any) -> str:
        output = response.output

        result = _safe_get(output, "result")
        if isinstance(result, dict):
            transcription_url = result.get("transcription_url")
            if isinstance(transcription_url, str) and transcription_url:
                return transcription_url

        results = _safe_get(output, "results")
        if isinstance(results, list):
            for item in results:
                if not isinstance(item, dict):
                    continue
                transcription_url = item.get("transcription_url")
                if isinstance(transcription_url, str) and transcription_url:
                    return transcription_url

        raise RuntimeError("Transcription succeeded but no transcription_url was returned")

    def _download_result(self, url: str, output_path: Path | str) -> Path:
        """Download transcription result JSON file."""
        output_path = Path(output_path)
        logger.info("Downloading transcription result to: %s", output_path)

        response = requests.get(url)
        response.raise_for_status()
        output_path.write_text(response.text, encoding="utf-8")

        logger.info("Transcription result saved to: %s", output_path)
        return output_path
