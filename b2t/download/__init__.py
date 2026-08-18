"""Download module."""

from b2t.download.platform import (
    Platform,
    PlatformDownloader,
    PlatformMetadata,
    sanitize_filename_component,
)
from b2t.download.url_detect import detect_platform, extract_platform_id
from b2t.download.xiaoyuzhou import XiaoyuzhouDownloader
from b2t.download.ximalaya import XimalayaDownloader
from b2t.download.yutto_api import download_audio

__all__ = [
    "Platform",
    "PlatformDownloader",
    "PlatformMetadata",
    "XiaoyuzhouDownloader",
    "XimalayaDownloader",
    "detect_platform",
    "download_audio",
    "extract_platform_id",
    "sanitize_filename_component",
]
