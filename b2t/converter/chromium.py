"""Shared Chromium launch configuration for Playwright converters."""

import os
from pathlib import Path

CHROMIUM_EXECUTABLE_PATH_ENV = "B2T_CHROMIUM_EXECUTABLE_PATH"


def chromium_launch_options() -> dict[str, str]:
    """Return Playwright launch options for an optional system Chromium."""
    configured_path = os.environ.get(CHROMIUM_EXECUTABLE_PATH_ENV, "").strip()
    if not configured_path:
        return {}

    executable_path = Path(configured_path).expanduser().resolve()
    if not executable_path.exists():
        raise RuntimeError(
            f"{CHROMIUM_EXECUTABLE_PATH_ENV} points to a missing file: "
            f"{executable_path}"
        )
    if not executable_path.is_file():
        raise RuntimeError(
            f"{CHROMIUM_EXECUTABLE_PATH_ENV} must point to an executable file: "
            f"{executable_path}"
        )
    if not os.access(executable_path, os.X_OK):
        raise RuntimeError(
            f"{CHROMIUM_EXECUTABLE_PATH_ENV} is not executable: {executable_path}"
        )

    return {"executable_path": str(executable_path)}
