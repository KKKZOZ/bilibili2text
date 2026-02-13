"""获取 Bilibili 视频元信息"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime

import httpx

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class VideoMetadata:
    """Bilibili 视频元信息"""

    bvid: str
    title: str
    author: str
    author_uid: int
    pubdate: str  # ISO 格式日期字符串 (YYYY-MM-DD HH:MM:SS)
    pubdate_timestamp: int  # Unix 时间戳
    description: str


async def get_video_metadata_async(bvid: str) -> VideoMetadata:
    """异步获取视频元信息

    Args:
        bvid: Bilibili 视频的 BV 号

    Returns:
        VideoMetadata: 视频元信息

    Raises:
        ValueError: BV 号格式错误
        httpx.HTTPError: API 请求失败
        RuntimeError: API 返回错误
    """
    if not bvid or not bvid.startswith("BV"):
        raise ValueError(f"无效的 BV 号: {bvid}")

    url = f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Referer": "https://www.bilibili.com"
    }

    logger.debug("正在获取视频 %s 的元信息...", bvid)

    async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
        response = await client.get(url, headers=headers)
        response.raise_for_status()

        data = response.json()

        if data.get("code") != 0:
            error_msg = data.get("message", "未知错误")
            raise RuntimeError(f"API 返回错误: {error_msg}")

        video_data = data.get("data")
        if not video_data:
            raise RuntimeError("API 返回数据为空")

        # 提取关键信息
        owner = video_data.get("owner", {})
        pubdate_timestamp = video_data.get("pubdate", 0)

        # 转换时间戳为可读格式
        pubdate_readable = ""
        if pubdate_timestamp:
            pubdate_readable = datetime.fromtimestamp(pubdate_timestamp).strftime('%Y-%m-%d %H:%M:%S')

        metadata = VideoMetadata(
            bvid=video_data.get("bvid", bvid),
            title=video_data.get("title", ""),
            author=owner.get("name", ""),
            author_uid=owner.get("mid", 0),
            pubdate=pubdate_readable,
            pubdate_timestamp=pubdate_timestamp,
            description=video_data.get("desc", ""),
        )

        logger.info(
            "成功获取视频元信息: %s (作者: %s, 发布时间: %s)",
            metadata.title,
            metadata.author,
            metadata.pubdate,
        )

        return metadata


def get_video_metadata(bvid: str) -> VideoMetadata:
    """同步获取视频元信息

    Args:
        bvid: Bilibili 视频的 BV 号

    Returns:
        VideoMetadata: 视频元信息

    Raises:
        ValueError: BV 号格式错误
        httpx.HTTPError: API 请求失败
        RuntimeError: API 返回错误或已有事件循环在运行
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass
    else:
        raise RuntimeError(
            "An event loop is already running; use get_video_metadata_async instead."
        )

    return asyncio.run(get_video_metadata_async(bvid))


__all__ = [
    "VideoMetadata",
    "get_video_metadata",
    "get_video_metadata_async",
]
