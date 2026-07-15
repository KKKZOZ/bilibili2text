import stat
from pathlib import Path

import pytest

from b2t.converter.chromium import (
    CHROMIUM_EXECUTABLE_PATH_ENV,
    chromium_launch_options,
)


def _create_executable(path: Path) -> Path:
    path.write_bytes(b"chrome")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def test_chromium_launch_options_keep_playwright_default_when_unset(
    monkeypatch,
) -> None:
    monkeypatch.delenv(CHROMIUM_EXECUTABLE_PATH_ENV, raising=False)

    assert chromium_launch_options() == {}


def test_chromium_launch_options_use_resolved_system_executable(
    monkeypatch, tmp_path: Path
) -> None:
    executable_path = _create_executable(tmp_path / "Google Chrome")
    monkeypatch.setenv(CHROMIUM_EXECUTABLE_PATH_ENV, str(executable_path))

    assert chromium_launch_options() == {
        "executable_path": str(executable_path.resolve())
    }


def test_chromium_launch_options_reject_invalid_path(
    monkeypatch, tmp_path: Path
) -> None:
    missing_path = tmp_path / "missing-chrome"
    monkeypatch.setenv(CHROMIUM_EXECUTABLE_PATH_ENV, str(missing_path))

    with pytest.raises(RuntimeError) as exc_info:
        chromium_launch_options()

    message = str(exc_info.value)
    assert CHROMIUM_EXECUTABLE_PATH_ENV in message
    assert str(missing_path) in message
    assert "missing file" in message
