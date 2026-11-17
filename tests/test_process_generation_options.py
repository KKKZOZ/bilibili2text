import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "web-ui"))

from backend.routes import process


@pytest.fixture
def client(monkeypatch):
    app = FastAPI()
    app.include_router(process.router)
    monkeypatch.setattr(process, "is_upload_enabled", lambda: True)
    return TestClient(app)


@pytest.mark.parametrize("upload", [False, True])
def test_rejects_both_disabled_before_creating_job(client, monkeypatch, upload):
    def unexpected_call(**kwargs):
        pytest.fail(
            "Invalid options must be rejected before runtime setup or job creation"
        )

    monkeypatch.setattr(process, "_ensure_runtime_ready", unexpected_call)
    monkeypatch.setattr(process, "_create_job", unexpected_call)
    if upload:
        response = client.post(
            "/api/process/upload",
            data={"skip_summary": "true", "auto_generate_fancy_html": "false"},
            files={"file": ("meeting.mp3", b"audio", "audio/mpeg")},
        )
    else:
        response = client.post(
            "/api/process",
            json={"url": "BV1ABcsztEcY", "skip_summary": True},
        )
    assert response.status_code == 400
    assert response.json()["detail"] == "总结和阅读报告至少需要开启一项"


@pytest.mark.parametrize(
    "skip_summary,report", [(False, False), (True, True), (False, True)]
)
@pytest.mark.parametrize("upload", [False, True])
def test_accepts_at_least_one_enabled(
    client, monkeypatch, skip_summary, report, upload
):
    captured = {}
    monkeypatch.setattr(process, "_ensure_runtime_ready", lambda **kwargs: None)
    monkeypatch.setattr(
        process, "_create_job", lambda **kwargs: {"job_id": "options-test"}
    )
    monkeypatch.setattr(
        process.job_manager, "submit", lambda *args, **kwargs: captured.update(kwargs)
    )
    monkeypatch.setattr(process, "is_open_public_mode", lambda: True)
    options = {"skip_summary": skip_summary, "auto_generate_fancy_html": report}
    if upload:
        response = client.post(
            "/api/process/upload",
            data={k: str(v).lower() for k, v in options.items()},
            files={"file": ("meeting.mp3", b"audio", "audio/mpeg")},
        )
    else:
        response = client.post("/api/process", json={"url": "BV1ABcsztEcY", **options})
    assert response.status_code == 200, response.text
    assert captured["skip_summary"] is skip_summary
    assert captured["auto_generate_fancy_html"] is report
