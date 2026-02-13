"""使用 yutto 下载 Bilibili 音频"""

import logging
import re
import subprocess
from pathlib import Path

from b2t.download.metadata import VideoMetadata, get_video_metadata

logger = logging.getLogger(__name__)

_BVID_PATTERN = re.compile(r"(BV[0-9A-Za-z]{10})", re.IGNORECASE)


def extract_bvid(raw: str) -> str | None:
    """从输入中提取 BV 号，提取失败返回 None。"""
    match = _BVID_PATTERN.search(raw.strip())
    if match is None:
        return None
    bvid = match.group(1)
    return "BV" + bvid[2:]


def normalize_bilibili_target(raw: str) -> str:
    """将输入标准化为 yutto 可直接处理的目标字符串。

    支持输入：
    - 完整 Bilibili URL（可带 query 参数）
    - 纯 BV 号
    """
    target = raw.strip()
    if not target:
        raise ValueError("URL 不能为空")

    bvid = extract_bvid(target)
    if bvid is None:
        return target

    return f"https://www.bilibili.com/video/{bvid}"


def download_audio(
    url: str,
    output_dir: Path | str,
    audio_quality: str = "30216",
    fetch_metadata: bool = True,
) -> tuple[Path, VideoMetadata | None]:
    """使用 yutto 下载音频文件

    Args:
        url: Bilibili 视频 URL
        output_dir: 输出目录
        audio_quality: 音频质量代码，默认 30216
        fetch_metadata: 是否获取视频元信息

    Returns:
        (音频文件路径, 视频元信息)
        如果 fetch_metadata 为 False 或获取失败，元信息为 None

    Raises:
        FileNotFoundError: 未找到下载的音频文件
        subprocess.CalledProcessError: yutto 下载失败
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    normalized_target = normalize_bilibili_target(url)
    logger.info("正在从 %s 下载音频...", normalized_target)

    # 获取元信息（如果需要）
    metadata = None
    if fetch_metadata:
        bvid = extract_bvid(url)
        if bvid:
            try:
                metadata = get_video_metadata(bvid)
            except Exception as e:
                logger.warning("获取视频元信息失败: %s", e)

    cmd = [
        "yutto",
        normalized_target,
        "--audio-only",
        "--audio-quality",
        audio_quality,
        "--dir",
        str(output_dir),
    ]

    result = subprocess.run(cmd, check=True, capture_output=True, text=True)
    logger.debug("yutto stdout: %s", result.stdout)
    logger.info("下载完成")

    # 查找下载的音频文件
    audio_files = (
        list(output_dir.glob("*.m4a"))
        + list(output_dir.glob("*.mp3"))
        + list(output_dir.glob("*.flac"))
    )

    if not audio_files:
        raise FileNotFoundError(f"未找到下载的音频文件: {output_dir}")

    audio_file = audio_files[0]
    logger.info("音频文件: %s", audio_file)

    return audio_file, metadata
