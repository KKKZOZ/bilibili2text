"""Centralized shared state, lazy singletons, and sys.path setup.

This module MUST be imported before any ``b2t.*`` imports so that the
project root is on ``sys.path``.
"""

from collections import OrderedDict
from dataclasses import replace
from datetime import datetime, timezone
import os
from pathlib import Path
import sys
from threading import Lock

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
from b2t.config import (  # noqa: E402
    AppConfig,
    STTConfig,
    STTProfile,
    SummarizeConfig,
    SummarizeModelProfile,
    load_config,
    resolve_summarize_api_base,
)
from b2t.history import HistoryDB  # noqa: E402
from b2t.storage import StorageBackend, StoredArtifact, create_storage_backend, create_stt_storage_backend  # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
WEB_UI_MODE_DEFAULT = "default"
WEB_UI_MODE_OPEN_PUBLIC = "open-public"
_WEB_UI_MODE_ENV = "B2T_WEB_UI_MODE"
_OPEN_PUBLIC_API_KEY_ENV = "B2T_OPEN_PUBLIC_API_KEY"

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
_stt_storage_backend: StorageBackend | None = None
_history_db: HistoryDB | None = None

try:
    _app_config: AppConfig | None = load_config(_ROOT_CONFIG_PATH)
except FileNotFoundError:
    _app_config = None

_web_ui_mode = os.environ.get(_WEB_UI_MODE_ENV, WEB_UI_MODE_DEFAULT).strip().lower()
if _web_ui_mode not in {WEB_UI_MODE_DEFAULT, WEB_UI_MODE_OPEN_PUBLIC}:
    _web_ui_mode = WEB_UI_MODE_DEFAULT

_public_api_key_lock = Lock()
_public_api_key = (
    os.environ.get(_OPEN_PUBLIC_API_KEY_ENV, "").strip()
    if _web_ui_mode == WEB_UI_MODE_OPEN_PUBLIC
    else ""
)

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


def _get_stt_storage_backend() -> StorageBackend:
    global _stt_storage_backend
    if _stt_storage_backend is not None:
        return _stt_storage_backend

    _stt_storage_backend = create_stt_storage_backend(_get_app_config())
    return _stt_storage_backend


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


def _get_web_ui_mode() -> str:
    return _web_ui_mode


def _is_open_public_mode() -> bool:
    return _web_ui_mode == WEB_UI_MODE_OPEN_PUBLIC


def _is_upload_enabled() -> bool:
    return not _is_open_public_mode()


def _is_delete_enabled() -> bool:
    return not _is_open_public_mode()


def _requires_user_api_key() -> bool:
    return _is_open_public_mode()


def _get_public_api_key() -> str:
    with _public_api_key_lock:
        return _public_api_key


def _set_public_api_key(api_key: str) -> None:
    cleaned = api_key.strip()
    global _public_api_key
    with _public_api_key_lock:
        _public_api_key = cleaned


def _clear_public_api_key() -> None:
    global _public_api_key
    with _public_api_key_lock:
        _public_api_key = ""


def _is_public_api_key_configured() -> bool:
    return bool(_get_public_api_key())


def _mask_api_key(api_key: str) -> str:
    if not api_key:
        return ""
    if len(api_key) <= 8:
        return "*" * len(api_key)
    return f"{api_key[:4]}{'*' * (len(api_key) - 8)}{api_key[-4:]}"


def _pick_qwen_stt_profile(stt: STTConfig) -> STTProfile:
    selected = stt.profiles.get(stt.profile)
    if selected is not None and selected.provider.strip().lower() == "qwen":
        return selected
    for profile in stt.profiles.values():
        if profile.provider.strip().lower() == "qwen":
            return profile
    return STTProfile(
        provider="qwen",
        language=stt.language,
        storage_profile=stt.storage_profile,
        qwen_api_key=stt.qwen_api_key,
        qwen_model=stt.qwen_model,
        qwen_base_url=stt.qwen_base_url,
        groq_api_key=stt.groq_api_key,
        groq_model=stt.groq_model,
        groq_base_url=stt.groq_base_url,
        groq_chunk_length=stt.groq_chunk_length,
        groq_overlap=stt.groq_overlap,
        groq_bitrate=stt.groq_bitrate,
    )


def _pick_bailian_summary_profile(summarize: SummarizeConfig) -> SummarizeModelProfile:
    selected = summarize.profiles.get(summarize.profile)
    if selected is not None and selected.provider.strip().lower() == "bailian":
        return selected
    for profile in summarize.profiles.values():
        if profile.provider.strip().lower() == "bailian":
            return profile
    return SummarizeModelProfile(
        provider="bailian",
        model="qwen3-max",
        api_key="",
        api_base="https://dashscope.aliyuncs.com/compatible-mode/v1",
        providers=(),
    )


def _build_open_public_config(config: AppConfig, api_key: str) -> AppConfig:
    base_stt_profile = _pick_qwen_stt_profile(config.stt)
    public_stt_profile = replace(
        base_stt_profile,
        provider="qwen",
        qwen_api_key=api_key,
        groq_api_key="",
    )
    public_stt_config = STTConfig(
        profile="open_public_qwen",
        profiles={"open_public_qwen": public_stt_profile},
        provider="qwen",
        language=public_stt_profile.language,
        storage_profile=public_stt_profile.storage_profile,
        qwen_api_key=api_key,
        qwen_model=public_stt_profile.qwen_model,
        qwen_base_url=public_stt_profile.qwen_base_url,
        groq_api_key="",
        groq_model=public_stt_profile.groq_model,
        groq_base_url=public_stt_profile.groq_base_url,
        groq_chunk_length=public_stt_profile.groq_chunk_length,
        groq_overlap=public_stt_profile.groq_overlap,
        groq_bitrate=public_stt_profile.groq_bitrate,
    )

    base_summary_profile = _pick_bailian_summary_profile(config.summarize)
    public_summary_profile = SummarizeModelProfile(
        provider="bailian",
        model=base_summary_profile.model,
        api_key=api_key,
        api_base=resolve_summarize_api_base(base_summary_profile),
        providers=(),
    )
    public_summarize_config = SummarizeConfig(
        profile="open_public_bailian",
        profiles={"open_public_bailian": public_summary_profile},
        enable_thinking=config.summarize.enable_thinking,
        preset=config.summarize.preset,
        presets_file=config.summarize.presets_file,
    )

    return replace(
        config,
        stt=public_stt_config,
        summarize=public_summarize_config,
    )


def _get_runtime_app_config(*, require_public_api_key: bool = False) -> AppConfig:
    config = _get_app_config()
    if not _is_open_public_mode():
        return config

    api_key = _get_public_api_key()
    if require_public_api_key and not api_key:
        raise ValueError(
            "open-public 模式下请先在「API Key」页面配置阿里云 DashScope API Key"
        )
    return _build_open_public_config(config, api_key)


def _get_runtime_features() -> dict[str, str | bool]:
    return {
        "mode": _get_web_ui_mode(),
        "allow_upload_audio": _is_upload_enabled(),
        "allow_delete": _is_delete_enabled(),
        "requires_user_api_key": _requires_user_api_key(),
        "api_key_configured": _is_public_api_key_configured(),
    }
