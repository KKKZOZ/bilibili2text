from types import SimpleNamespace

import pytest

from b2t.config import STTProfile
from b2t.stt.qwen_asr import QwenSTTProvider


class _DictLikeOutput(dict):
    def __getattr__(self, attr):
        return self[attr]


class _DummyStorageBackend:
    def supports_public_url(self) -> bool:
        return True


def _provider(
    model: str,
    *,
    diarization_enabled: bool = False,
    speaker_count: int = 2,
) -> QwenSTTProvider:
    return QwenSTTProvider(
        STTProfile(
            provider="qwen",
            qwen_api_key="test-key",
            qwen_model=model,
            qwen_base_url="https://dashscope.aliyuncs.com/api/v1",
            language="zh",
            diarization_enabled=diarization_enabled,
            speaker_count=speaker_count,
        ),
        _DummyStorageBackend(),
    )


def test_submit_task_uses_fun_asr_api(monkeypatch) -> None:
    provider = _provider("fun-asr")
    captured = {}

    def fake_async_call(**kwargs):
        captured["kwargs"] = kwargs
        return SimpleNamespace(output=SimpleNamespace(task_id="task-fun"))

    def fake_wait(*, task):
        captured["task"] = task
        return SimpleNamespace(
            output={
                "results": [
                    {
                        "subtask_status": "SUCCEEDED",
                        "transcription_url": "https://example.com/fun.json",
                    }
                ]
            }
        )

    monkeypatch.setattr("b2t.stt.qwen_asr.Transcription.async_call", fake_async_call)
    monkeypatch.setattr("b2t.stt.qwen_asr.Transcription.wait", fake_wait)

    response = provider._submit_task("https://example.com/audio.wav")

    assert captured["kwargs"] == {
        "model": "fun-asr",
        "file_urls": ["https://example.com/audio.wav"],
        "language_hints": ["zh"],
    }
    assert captured["task"] == "task-fun"
    assert provider._extract_task_status(response) == "SUCCEEDED"
    assert (
        provider._extract_transcription_url(response) == "https://example.com/fun.json"
    )


def test_submit_task_enables_diarization_only_for_fun_asr(monkeypatch) -> None:
    provider = _provider(
        "fun-asr",
        diarization_enabled=True,
        speaker_count=3,
    )
    captured = {}

    def fake_async_call(**kwargs):
        captured["kwargs"] = kwargs
        return SimpleNamespace(output=SimpleNamespace(task_id="task-fun"))

    monkeypatch.setattr("b2t.stt.qwen_asr.Transcription.async_call", fake_async_call)
    monkeypatch.setattr(
        "b2t.stt.qwen_asr.Transcription.wait",
        lambda *, task: SimpleNamespace(output={"task_status": "SUCCEEDED"}),
    )

    provider._submit_task("https://example.com/audio.wav")

    assert captured["kwargs"] == {
        "model": "fun-asr",
        "file_urls": ["https://example.com/audio.wav"],
        "language_hints": ["zh"],
        "diarization_enabled": True,
        "speaker_count": 3,
    }


def test_extract_transcription_url_supports_dashscope_dict_mixin_shape() -> None:
    provider = _provider("fun-asr")
    response = SimpleNamespace(
        output=_DictLikeOutput(
            task_status="SUCCEEDED",
            results=[
                {
                    "subtask_status": "SUCCEEDED",
                    "transcription_url": "https://example.com/fun.json",
                }
            ],
        )
    )

    assert provider._extract_task_status(response) == "SUCCEEDED"
    assert (
        provider._extract_transcription_url(response) == "https://example.com/fun.json"
    )


def test_submit_task_uses_qwen_filetrans_api(monkeypatch) -> None:
    provider = _provider(
        "qwen3-asr-flash-filetrans",
        diarization_enabled=True,
        speaker_count=3,
    )
    captured = {}

    def fake_async_call(**kwargs):
        captured["kwargs"] = kwargs
        return SimpleNamespace(output=SimpleNamespace(task_id="task-qwen"))

    def fake_wait(*, task):
        captured["task"] = task
        return SimpleNamespace(
            output=SimpleNamespace(
                task_status="SUCCEEDED",
                result={"transcription_url": "https://example.com/qwen.json"},
            )
        )

    monkeypatch.setattr(
        "b2t.stt.qwen_asr.QwenTranscription.async_call",
        fake_async_call,
    )
    monkeypatch.setattr("b2t.stt.qwen_asr.QwenTranscription.wait", fake_wait)

    response = provider._submit_task("https://example.com/audio.wav")

    assert captured["kwargs"] == {
        "model": "qwen3-asr-flash-filetrans",
        "file_url": "https://example.com/audio.wav",
        "language": "zh",
        "enable_itn": True,
        "enable_words": True,
    }
    assert captured["task"] == "task-qwen"
    assert provider._extract_task_status(response) == "SUCCEEDED"
    assert (
        provider._extract_transcription_url(response) == "https://example.com/qwen.json"
    )


def test_submit_task_reports_dashscope_submission_error(monkeypatch) -> None:
    provider = _provider("fun-asr")

    def fake_async_call(**kwargs):
        return SimpleNamespace(
            status_code=400,
            code="InvalidApiKey",
            message="API key is invalid",
            request_id="req-1",
            output=None,
        )

    monkeypatch.setattr("b2t.stt.qwen_asr.Transcription.async_call", fake_async_call)

    with pytest.raises(RuntimeError) as exc_info:
        provider._submit_task("https://example.com/audio.wav")

    message = str(exc_info.value)
    assert "DashScope transcription task submission failed" in message
    assert "code=InvalidApiKey" in message
    assert "message=API key is invalid" in message
