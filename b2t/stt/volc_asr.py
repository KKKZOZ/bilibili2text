"""Volcengine audio file transcription via asynchronous submit/query APIs."""

from __future__ import annotations

import json
import logging
from pathlib import Path
import subprocess
import time
from typing import Any
from uuid import uuid4

import requests

from b2t.config import STTConfig
from b2t.storage.base import StorageBackend
from b2t.stt.base import ProgressCallback, STTProvider

logger = logging.getLogger(__name__)

_PENDING_STATUS_CODES = {"20000001", "20000002"}
_SUCCESS_STATUS_CODE = "20000000"
_DIRECT_FORMATS: dict[str, str] = {
    ".mp3": "mp3",
    ".ogg": "ogg",
    ".pcm": "raw",
    ".raw": "raw",
    ".wav": "wav",
}
_LANGUAGE_ALIASES = {
    "en": "en-US",
    "ja": "ja-JP",
    "yue": "yue-CN",
    "zh": "zh-CN",
}


def _header_value(headers: requests.structures.CaseInsensitiveDict, key: str) -> str:
    value = headers.get(key, "")
    return value.strip() if isinstance(value, str) else ""


def _resolve_language(language: str) -> str:
    normalized = language.strip()
    if not normalized:
        return ""
    return _LANGUAGE_ALIASES.get(normalized.lower(), normalized)


def _raise_api_error(response: requests.Response, operation: str) -> None:
    status_code = _header_value(response.headers, "X-Api-Status-Code")
    message = _header_value(response.headers, "X-Api-Message")
    body = response.text.strip()
    body_snippet = body[:500] if body else ""
    detail = f"{operation} failed: http={response.status_code}"
    if status_code:
        detail += f", status={status_code}"
    if message:
        detail += f", message={message}"
    if body_snippet:
        detail += f", body={body_snippet}"
    raise RuntimeError(detail)


class VolcSTTProvider(STTProvider):
    """Volcengine STT provider backed by the bigmodel submit/query APIs."""

    def __init__(self, stt_config: STTConfig, storage_backend: StorageBackend) -> None:
        self._stt_config = stt_config
        self._storage_backend = storage_backend
        self._session = requests.Session()

    def transcribe(
        self,
        audio_path: Path,
        work_dir: Path,
        progress_callback: ProgressCallback | None = None,
    ) -> Path:
        def emit(stage: str, label: str, progress: int) -> None:
            if progress_callback is not None:
                progress_callback(stage, label, progress)

        if not self._stt_config.volc_api_key:
            raise ValueError("Missing stt.volc_api_key config")
        if not self._storage_backend.supports_public_url():
            raise ValueError(
                "Volc transcription requires a storage backend that supports public URLs for audio upload. "
                "Please set the storage_profile for the current stt.profile (or storage.backend) to minio or alicloud."
            )

        json_path = work_dir / f"{audio_path.stem}_transcription.json"
        emit("transcribing", "Speech transcription", 35)

        prepared_audio_path, audio_format = self._prepare_audio(audio_path, work_dir)
        try:
            with self._storage_backend.temporary_public_url(
                prepared_audio_path
            ) as audio_url:
                emit("transcribing", "Speech transcription", 50)
                task_id = str(uuid4())
                self._submit_task(
                    audio_url=audio_url, audio_format=audio_format, task_id=task_id
                )
                emit("transcribing", "Speech transcription", 65)
                result = self._poll_result(task_id)
                json_path.write_text(
                    json.dumps(result, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
        finally:
            if prepared_audio_path != audio_path:
                prepared_audio_path.unlink(missing_ok=True)

        return json_path

    def _prepare_audio(self, audio_path: Path, work_dir: Path) -> tuple[Path, str]:
        format_name = _DIRECT_FORMATS.get(audio_path.suffix.lower())
        if format_name is not None:
            return audio_path, format_name

        converted_path = work_dir / f"{audio_path.stem}_volc.mp3"
        logger.info(
            "Converting unsupported audio format %s to mp3 for Volc transcription",
            audio_path.suffix or "(no suffix)",
        )
        command = [
            "ffmpeg",
            "-y",
            "-i",
            str(audio_path),
            "-vn",
            "-ar",
            "16000",
            "-ac",
            "1",
            "-c:a",
            "libmp3lame",
            "-b:a",
            "128k",
            str(converted_path),
        ]
        try:
            subprocess.run(command, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(
                f"Failed to convert audio for Volc transcription: {exc.stderr.strip() or exc}"
            ) from exc
        return converted_path, "mp3"

    def _submit_task(self, *, audio_url: str, audio_format: str, task_id: str) -> None:
        headers = {
            "Content-Type": "application/json",
            "X-Api-Key": self._stt_config.volc_api_key,
            "X-Api-Resource-Id": self._stt_config.volc_resource_id,
            "X-Api-Request-Id": task_id,
            "X-Api-Sequence": "-1",
        }
        payload: dict[str, Any] = {
            "user": {
                "uid": "b2t",
            },
            "audio": {
                "format": audio_format,
                "url": audio_url,
                "codec": "raw",
                "rate": 16000,
                "bits": 16,
                "channel": 1,
            },
            "request": {
                "model_name": "bigmodel",
                "enable_itn": self._stt_config.volc_enable_itn,
                "enable_punc": self._stt_config.volc_enable_punc,
                "enable_ddc": self._stt_config.volc_enable_ddc,
                "show_utterances": self._stt_config.volc_show_utterances,
            },
        }
        language = _resolve_language(self._stt_config.language)
        if language:
            payload["audio"]["language"] = language

        response = self._session.post(
            self._stt_config.volc_submit_url,
            headers=headers,
            json=payload,
            timeout=60,
        )
        if not response.ok:
            _raise_api_error(response, "Volc submit")

        status_code = _header_value(response.headers, "X-Api-Status-Code")
        message = _header_value(response.headers, "X-Api-Message")
        if status_code != _SUCCESS_STATUS_CODE:
            raise RuntimeError(
                f"Volc submit failed: status={status_code or 'unknown'}, message={message or 'unknown'}"
            )

        logger.info("Volc task submitted successfully, task_id=%s", task_id)

    def _poll_result(self, task_id: str) -> dict[str, Any]:
        headers = {
            "Content-Type": "application/json",
            "X-Api-Key": self._stt_config.volc_api_key,
            "X-Api-Resource-Id": self._stt_config.volc_resource_id,
            "X-Api-Request-Id": task_id,
        }

        deadline = time.monotonic() + self._stt_config.volc_timeout_seconds
        last_status_code = ""
        last_message = ""
        while time.monotonic() < deadline:
            response = self._session.post(
                self._stt_config.volc_query_url,
                headers=headers,
                json={},
                timeout=60,
            )
            if not response.ok:
                _raise_api_error(response, "Volc query")

            status_code = _header_value(response.headers, "X-Api-Status-Code")
            message = _header_value(response.headers, "X-Api-Message")
            last_status_code = status_code
            last_message = message

            if status_code == _SUCCESS_STATUS_CODE:
                data = response.json()
                logger.info("Volc task completed, task_id=%s", task_id)
                return data
            if status_code not in _PENDING_STATUS_CODES:
                raise RuntimeError(
                    f"Volc query failed: status={status_code or 'unknown'}, message={message or 'unknown'}"
                )

            logger.info(
                "Volc task still running, task_id=%s, status=%s, message=%s",
                task_id,
                status_code,
                message or "",
            )
            time.sleep(self._stt_config.volc_poll_interval_seconds)

        raise TimeoutError(
            "Volc transcription timed out after "
            f"{self._stt_config.volc_timeout_seconds}s "
            f"(last status={last_status_code or 'unknown'}, message={last_message or 'unknown'})"
        )
