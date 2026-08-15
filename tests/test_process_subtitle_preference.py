import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "web-ui"))

from backend.routes import process
from backend.schemas import ProcessRequest

from b2t.download.comments import DEFAULT_COMMENT_LIMIT


def test_process_comment_limit_matches_shared_default() -> None:
    request = ProcessRequest(url="BV1ABcsztEcY")

    assert DEFAULT_COMMENT_LIMIT == 200
    assert request.comment_limit == DEFAULT_COMMENT_LIMIT


def test_process_video_passes_bilibili_subtitle_preference(monkeypatch) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(process, "_ensure_runtime_ready", lambda **kwargs: None)
    monkeypatch.setattr(
        process,
        "_create_job",
        lambda **kwargs: {"job_id": "job-subtitle"},
    )

    def fake_submit_job(fn, **kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(process, "submit_job", fake_submit_job)

    response = process.process_video(
        ProcessRequest(
            url="BV1ABcsztEcY",
            skip_summary=True,
            prefer_bilibili_subtitle=False,
        )
    )

    assert response.job_id == "job-subtitle"
    assert captured["prefer_bilibili_subtitle"] is False


def test_process_video_defaults_to_bilibili_subtitle_preference(monkeypatch) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(process, "_ensure_runtime_ready", lambda **kwargs: None)
    monkeypatch.setattr(
        process,
        "_create_job",
        lambda **kwargs: {"job_id": "job-default"},
    )
    monkeypatch.setattr(
        process, "submit_job", lambda fn, **kwargs: captured.update(kwargs)
    )

    process.process_video(ProcessRequest(url="BV1ABcsztEcY", skip_summary=True))

    assert captured["prefer_bilibili_subtitle"] is True
