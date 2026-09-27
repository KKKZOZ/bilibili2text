import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from b2t.backend import run_backend
from b2t.config import BackendConfig, _load_backend_config


def test_backend_config_defaults_and_normalization():
    assert _load_backend_config({}) == BackendConfig()
    result = _load_backend_config(
        {
            "host": " 127.0.0.1 ",
            "port": 9000,
            "cors_origins": [" https://site.example/ ", "https://site.example"],
        }
    )
    assert result.host == "127.0.0.1"
    assert result.port == 9000
    assert result.cors_origins == ("https://site.example",)


@pytest.mark.parametrize(
    "raw",
    [
        {"port": 0},
        {"port": 65536},
        {"port": True},
        {"host": ""},
        {"cors_origins": "https://site.example"},
        {"cors_origins": ["*"]},
        {"cors_origins": ["https://site.example/path"]},
        {"unknown": 1},
    ],
)
def test_invalid_backend_config(raw):
    with pytest.raises(ValueError):
        _load_backend_config(raw)


def test_backend_launch_uses_config_and_propagates_config_path(monkeypatch, tmp_path):
    import uvicorn

    config_path = tmp_path / "custom.toml"
    monkeypatch.setenv("B2T_CONFIG", "original")
    seen = {}

    def load(path):
        seen["path"] = path
        return SimpleNamespace(backend=BackendConfig(host="0.0.0.0", port=9123))

    def launch(app, **kwargs):
        seen.update(app=app, **kwargs)

    monkeypatch.setattr("b2t.backend.load_config", load)
    monkeypatch.setattr(uvicorn, "run", launch)
    monkeypatch.setattr(sys, "path", list(sys.path))
    run_backend(str(config_path))
    assert seen == {
        "path": str(config_path),
        "app": "backend.main:app",
        "host": "0.0.0.0",
        "port": 9123,
    }
    assert os.environ["B2T_CONFIG"] == str(config_path.resolve())
    assert (Path(sys.path[0]) / "backend" / "main.py").is_file() or any(
        (Path(p) / "backend" / "main.py").is_file() for p in sys.path
    )


def test_default_backend_mode_is_open_public():
    environment = dict(os.environ)
    environment.pop("B2T_WEB_UI_MODE", None)
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; sys.path.insert(0, 'web-ui'); from backend.settings import get_web_ui_mode; print(get_web_ui_mode())",
        ],
        env=environment,
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "open-public"
