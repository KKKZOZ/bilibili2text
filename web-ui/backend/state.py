"""Backward-compatible exports for older backend modules.

New code should import from ``settings``, ``dependencies``, ``job_store``, or
``download_registry`` directly.
"""

from backend.dependencies import (
    get_history_db as _get_history_db,
    get_rag_store as _get_rag_store,
    get_storage_backend as _get_storage_backend,
    get_stt_storage_backend as _get_stt_storage_backend,
)
from backend.download_registry import download_registry
from backend.job_store import JobValue, job_repository
from backend.settings import (
    JOB_LOG_LIMIT,
    STAGE_KEYS,
    build_open_public_config as _build_open_public_config,
    clear_public_api_key as _clear_public_api_key,
    get_app_config as _get_app_config,
    get_public_api_key as _get_public_api_key,
    get_runtime_app_config as _get_runtime_app_config,
    get_runtime_features as _get_runtime_features,
    get_web_ui_mode as _get_web_ui_mode,
    is_delete_enabled as _is_delete_enabled,
    is_open_public_mode as _is_open_public_mode,
    is_public_api_key_configured as _is_public_api_key_configured,
    is_upload_enabled as _is_upload_enabled,
    mask_api_key as _mask_api_key,
    requires_user_api_key as _requires_user_api_key,
    set_public_api_key as _set_public_api_key,
    utc_iso as _utc_iso,
)

WEB_UI_MODE_DEFAULT = "default"
WEB_UI_MODE_OPEN_PUBLIC = "open-public"

_download_index = download_registry.legacy_artifacts
_download_lock = download_registry.legacy_lock
_download_limit = 100

_job_index = job_repository.legacy_jobs
_job_lock = job_repository.legacy_lock
_job_limit = 200
