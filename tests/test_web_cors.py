import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "web-ui"))

from backend.cors import configure_cors


def make_client() -> TestClient:
    app = FastAPI()
    configure_cors(app)

    @app.get("/api/health")
    def health():
        return {"ok": True}

    return TestClient(app)


def test_pages_preflight_and_response(monkeypatch):
    monkeypatch.setenv(
        "B2T_CORS_ORIGINS", " https://b2t.pages.dev/, https://b2t.example.com, "
    )
    client = make_client()
    for origin in ("https://b2t.pages.dev", "https://b2t.example.com"):
        response = client.options(
            "/api/process",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == origin
        response = client.get("/api/health", headers={"Origin": origin})
        assert response.headers["access-control-allow-origin"] == origin
        assert "Origin" in response.headers["vary"]


def test_unlisted_origin_is_not_allowed(monkeypatch):
    monkeypatch.setenv("B2T_CORS_ORIGINS", "https://b2t.pages.dev")
    client = make_client()
    for origin in ("https://other.pages.dev", "http://localhost:6010"):
        response = client.options(
            "/api/history/run",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "DELETE",
            },
        )
        assert response.status_code == 400
        assert "access-control-allow-origin" not in response.headers


def test_default_local_origins(monkeypatch):
    monkeypatch.delenv("B2T_CORS_ORIGINS", raising=False)
    client = make_client()
    for port in (5173, 6010):
        for host in ("localhost", "127.0.0.1"):
            origin = f"http://{host}:{port}"
            response = client.get("/api/health", headers={"Origin": origin})
            assert response.headers["access-control-allow-origin"] == origin
