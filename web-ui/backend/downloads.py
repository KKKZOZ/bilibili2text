"""Compatibility helpers for download registration."""

from backend.download_registry import download_registry, media_type_for_filename

_content_cache = download_registry.legacy_content
_content_cache_lock = download_registry.legacy_lock
_content_cache_limit = 100


def _store_download(artifact) -> str:
    return download_registry.store_artifact(artifact)


def _store_content_download(content: bytes, filename: str) -> str:
    return download_registry.store_content(content, filename)


def _media_type_for_filename(filename: str) -> str:
    return media_type_for_filename(filename)
