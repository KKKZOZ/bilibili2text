"""Download module."""

from b2t.download.yutto_api import download_audio
from b2t.download.platform import (
    Platform,
    PlatformDownloader,
    PlatformMetadata,
    sanitize_filename_component,
)
from b2t.download.url_detect import detect_platform, extract_platform_id
from b2t.download.xiaoyuzhou import XiaoyuzhouDownloader
from b2t.download.ximalaya import XimalayaDownloader

__all__ = [
    "download_audio",
    "Platform",
    "PlatformDownloader",
    "PlatformMetadata",
    "sanitize_filename_component",
    "detect_platform",
    "extract_platform_id",
    "XiaoyuzhouDownloader",
    "XimalayaDownloader",
]
