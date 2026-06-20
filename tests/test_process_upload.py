from pathlib import Path
import sys

from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "web-ui"))

from backend.routes import process  # noqa: E402


class _FakeUploadFile:
    def __init__(self, *, filename: str, content: bytes) -> None:
        self.filename = filename
        self.file = self
        self._content = content
        self._offset = 0
        self.closed = False

    def read(self, size: int = -1) -> bytes:
        if self._offset >= len(self._content):
            return b""
        if size < 0:
            size = len(self._content) - self._offset
        chunk = self._content[self._offset : self._offset + size]
        self._offset += len(chunk)
        return chunk

    def close(self) -> None:
        self.closed = True


def test_open_public_upload_accepts_plain_audio_filename(monkeypatch) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(process, "is_upload_enabled", lambda: True)
    monkeypatch.setattr(process, "is_open_public_mode", lambda: True)
    monkeypatch.setattr(process, "_ensure_runtime_ready", lambda **kwargs: None)
    monkeypatch.setattr(
        process,
        "_create_job",
        lambda **kwargs: {"job_id": "abc123"},
    )

    def fake_submit_job(fn, **kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(process, "submit_job", fake_submit_job)

    response = process.process_uploaded_audio(
        file=_FakeUploadFile(filename="meeting.mp3", content=b"audio"),
        skip_summary=True,
        summary_preset=None,
        summary_profile=None,
        summary_prompt_template=None,
        auto_generate_fancy_html=False,
        api_key=None,
        deepseek_api_key=None,
    )

    assert response.job_id == "abc123"
    assert captured["input_bvid"] == "upload-abc123"
    assert captured["ephemeral_upload"] is True
    assert str(captured["input_audio_path"]).endswith("meeting.mp3")


def test_default_upload_still_requires_bv_audio_filename(monkeypatch) -> None:
    monkeypatch.setattr(process, "is_upload_enabled", lambda: True)
    monkeypatch.setattr(process, "is_open_public_mode", lambda: False)
    monkeypatch.setattr(process, "_ensure_runtime_ready", lambda **kwargs: None)

    try:
        process.process_uploaded_audio(
            file=_FakeUploadFile(filename="meeting.mp3", content=b"audio"),
            skip_summary=True,
            summary_preset=None,
            summary_profile=None,
            summary_prompt_template=None,
            auto_generate_fancy_html=False,
            api_key=None,
            deepseek_api_key=None,
        )
    except HTTPException as exc:
        assert exc.status_code == 400
        assert "BV号_视频标题" in str(exc.detail)
    else:
        raise AssertionError("expected default upload filename validation to fail")


def test_open_public_video_upload_converts_before_submit(monkeypatch, tmp_path) -> None:
    captured: dict[str, object] = {}
    converted = tmp_path / "converted.wav"
    converted.write_bytes(b"wav")

    monkeypatch.setattr(process, "is_upload_enabled", lambda: True)
    monkeypatch.setattr(process, "is_open_public_mode", lambda: True)
    monkeypatch.setattr(process, "_ensure_runtime_ready", lambda **kwargs: None)
    monkeypatch.setattr(
        process, "_convert_video_upload_to_audio", lambda path: converted
    )
    monkeypatch.setattr(
        process,
        "_create_job",
        lambda **kwargs: {"job_id": "video123"},
    )

    def fake_submit_job(fn, **kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(process, "submit_job", fake_submit_job)

    response = process.process_uploaded_audio(
        file=_FakeUploadFile(filename="clip.mp4", content=b"video"),
        skip_summary=True,
        summary_preset=None,
        summary_profile=None,
        summary_prompt_template=None,
        auto_generate_fancy_html=False,
        api_key=None,
        deepseek_api_key=None,
    )

    assert response.job_id == "video123"
    assert captured["input_audio_path"] == str(converted)
    assert captured["input_bvid"] == "upload-video123"
    assert captured["ephemeral_upload"] is True
