"""Backward-compatible exports for older backend modules.

New code should import from ``settings``, ``dependencies``, ``job_store``, or
``download_registry`` directly.
"""

from backend.download_registry import download_registry
from backend.job_store import job_repository

WEB_UI_MODE_DEFAULT = "default"
WEB_UI_MODE_OPEN_PUBLIC = "open-public"

_download_index = download_registry.legacy_artifacts
_download_lock = download_registry.legacy_lock
_download_limit = 100

_job_index = job_repository.legacy_jobs
_job_lock = job_repository.legacy_lock
_job_limit = 200
