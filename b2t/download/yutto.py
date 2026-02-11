"""使用 yutto 下载 Bilibili 音频"""

import logging
import subprocess
from pathlib import Path

from b2t.config import DownloadConfig

logger = logging.getLogger(__name__)


def download_audio(
    url: str,
    output_dir: Path | str,
    audio_quality: str = "30216",
) -> Path:
    """使用 yutto 下载音频文件

    Args:
        url: Bilibili 视频 URL
        output_dir: 输出目录
        audio_quality: 音频质量代码，默认 30216

    Returns:
        下载的音频文件路径

    Raises:
        FileNotFoundError: 未找到下载的音频文件
        subprocess.CalledProcessError: yutto 下载失败
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info("正在从 %s 下载音频...", url)

    cmd = [
        "yutto",
        url,
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

    return audio_file
