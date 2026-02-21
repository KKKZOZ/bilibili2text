"""Centralized shared state, lazy singletons, and sys.path setup.

This module MUST be imported before any ``b2t.*`` imports so that the
project root is on ``sys.path``.
"""

from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
import sys
from threading import Lock
from typing import TYPE_CHECKING

# ---------------------------------------------------------------------------
# sys.path setup – make ``b2t`` importable regardless of working directory
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
_ROOT_CONFIG_PATH = _PROJECT_ROOT / "config.toml"

# ---------------------------------------------------------------------------
# Imports that depend on the sys.path setup above
# ---------------------------------------------------------------------------
from b2t.config import AppConfig, load_config  # noqa: E402
from b2t.history import HistoryDB  # noqa: E402
from b2t.storage import StorageBackend, StoredArtifact, create_storage_backend  # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
STAGE_KEYS = (
    "queued",
    "downloading",
    "transcribing",
    "converting",
    "summarizing",
    "completed",
)

JOB_LOG_LIMIT = 400

JobValue = (
    str
    | int
    | float
    | bool
    | None
    | list[str]
    | list[dict[str, str]]
    | dict[str, int]
    | dict[str, bool]
    | dict[str, str]
)

# ---------------------------------------------------------------------------
# Mutable shared state
# ---------------------------------------------------------------------------
_download_index: OrderedDict[str, StoredArtifact] = OrderedDict()
_download_lock = Lock()
_download_limit = 100

_job_index: OrderedDict[str, dict[str, JobValue]] = OrderedDict()
_job_lock = Lock()
_job_limit = 200

_storage_backend: StorageBackend | None = None
_history_db: HistoryDB | None = None

try:
    _app_config: AppConfig | None = load_config(_ROOT_CONFIG_PATH)
except FileNotFoundError:
    _app_config = None

# ---------------------------------------------------------------------------
# Lazy singleton getters
# ---------------------------------------------------------------------------


def _get_app_config() -> AppConfig:
    global _app_config
    if _app_config is not None:
        return _app_config

    _app_config = load_config(_ROOT_CONFIG_PATH)
    return _app_config


def _get_storage_backend() -> StorageBackend:
    global _storage_backend
    if _storage_backend is not None:
        return _storage_backend

    _storage_backend = create_storage_backend(_get_app_config())
    return _storage_backend


def _get_history_db() -> HistoryDB:
    global _history_db
    if _history_db is not None:
        return _history_db

    config = _get_app_config()
    db_dir = config.download.db_dir
    _history_db = HistoryDB(db_dir)
    return _history_db


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _utc_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()
