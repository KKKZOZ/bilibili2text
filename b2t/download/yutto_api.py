"""Download Bilibili audio using yutto Python API (default implementation)"""

from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path
from typing import Any

from yutto.cli.cli import add_download_arguments
from yutto.cli.settings import YuttoSettings
from yutto.download_manager import DownloadManager, DownloadTask
from yutto.utils.fetcher import FetcherContext
from yutto.validator import initial_validation, validate_basic_arguments

from b2t.download.metadata import VideoMetadata, get_video_metadata_async
from b2t.download.yutto_cli import extract_bvid, normalize_bilibili_target

logger = logging.getLogger(__name__)

_AUDIO_SUFFIXES = {".m4a", ".mp3", ".flac"}


class MinimalYuttoError(RuntimeError):
    """Raised when the minimal API exits with a non-zero code."""

    exit_code: int

    def __init__(self, exit_code: int):
        self.exit_code = exit_code
        super().__init__(f"minimal yutto failed with exit code {exit_code}")


def _build_minimal_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="yutto-minimal",
        description="Minimal yutto API for low-quality audio downloads",
    )
    settings = YuttoSettings()  # pyright: ignore[reportCallIssue]
    add_download_arguments(parser, settings)
    return parser


def _build_minimal_argv(
    url: str,
    output_dir: Path,
    overwrite: bool,
    audio_quality: str,
) -> list[str]:
    argv = [
        url,
        "--audio-only",
        "--audio-quality",
        audio_quality,
        "--no-danmaku",
        "--no-subtitle",
        "--no-cover",
        "--no-chapter-info",
        "--no-progress",
        "--no-color",
        "-d",
        str(output_dir),
    ]
    if overwrite:
        argv.append("--overwrite")
    return argv


def _normalize_exit_code(code: Any) -> int:
    if isinstance(code, int):
        return code
    return 1


def _collect_audio_files(output_dir: Path) -> list[Path]:
    return sorted(
        (
            file
            for file in output_dir.rglob("*")
            if file.is_file() and file.suffix.lower() in _AUDIO_SUFFIXES
        ),
        key=lambda file: file.stat().st_mtime,
        reverse=True,
    )


async def download_audio_minimal_async(
    url: str,
    output_dir: str | Path = ".",
    *,
    overwrite: bool = False,
    audio_quality: str = "30216",
    fetch_metadata: bool = True,
) -> VideoMetadata | None:
    """Download audio for one URL via yutto's internal API.

    Args:
        url: Bilibili video URL or BV ID
        output_dir: Output directory
        overwrite: Whether to overwrite existing files
        audio_quality: Audio quality code
        fetch_metadata: Whether to fetch video metadata

    Returns:
        VideoMetadata if fetch_metadata is True, otherwise None
    """
    # Fetch metadata (if needed)
    metadata = None
    if fetch_metadata:
        bvid = extract_bvid(url)
        if bvid:
            try:
                metadata = await get_video_metadata_async(bvid)
            except Exception as e:
                logger.warning("Failed to fetch video metadata: %s", e)

    parser = _build_minimal_parser()
    output_dir_path = Path(output_dir).expanduser()
    args = parser.parse_args(
        _build_minimal_argv(url, output_dir_path, overwrite, audio_quality)
    )
    ctx = FetcherContext()
    manager = DownloadManager()

    try:
        initial_validation(ctx, args)
        validate_basic_arguments(args)
        manager.start(ctx)
        await manager.add_task(DownloadTask(args=args))
        await manager.add_stop_task()
        await manager.wait_for_completion()
    except SystemExit as e:
        raise MinimalYuttoError(_normalize_exit_code(e.code)) from e

    return metadata


def download_audio_minimal(
    url: str,
    output_dir: str | Path = ".",
    *,
    overwrite: bool = False,
    audio_quality: str = "30216",
    fetch_metadata: bool = True,
) -> VideoMetadata | None:
    """Synchronous wrapper of `download_audio_minimal_async`.

    Args:
        url: Bilibili video URL or BV ID
        output_dir: Output directory
        overwrite: Whether to overwrite existing files
        audio_quality: Audio quality code
        fetch_metadata: Whether to fetch video metadata

    Returns:
        VideoMetadata if fetch_metadata is True, otherwise None
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass
    else:
        raise RuntimeError(
            "An event loop is already running; use download_audio_minimal_async instead."
        )
    return asyncio.run(
        download_audio_minimal_async(
            url,
            output_dir=output_dir,
            overwrite=overwrite,
            audio_quality=audio_quality,
            fetch_metadata=fetch_metadata,
        )
    )


def download_audio(
    url: str,
    output_dir: Path | str,
    audio_quality: str = "30216",
    fetch_metadata: bool = True,
) -> tuple[Path, VideoMetadata | None]:
    """Download audio file using yutto API.

    Args:
        url: Bilibili video URL or BV ID
        output_dir: Output directory
        audio_quality: Audio quality code
        fetch_metadata: Whether to fetch video metadata

    Returns:
        Tuple of (audio_file_path, metadata)
        metadata is None if fetch_metadata is False or fetching failed
    """
    output_dir_path = Path(output_dir)
    output_dir_path.mkdir(parents=True, exist_ok=True)

    normalized_target = normalize_bilibili_target(url)
    logger.info("Downloading audio from %s...", normalized_target)

    existing_files = {path.resolve() for path in _collect_audio_files(output_dir_path)}
    metadata = download_audio_minimal(
        normalized_target,
        output_dir=output_dir_path,
        audio_quality=audio_quality,
        fetch_metadata=fetch_metadata,
    )
    logger.info("Download complete")

    audio_files = [
        path
        for path in _collect_audio_files(output_dir_path)
        if path.resolve() not in existing_files
    ]
    if not audio_files:
        audio_files = _collect_audio_files(output_dir_path)
    if not audio_files:
        raise FileNotFoundError(f"No downloaded audio files found: {output_dir_path}")

    audio_file = audio_files[0]
    logger.info("Audio file: %s", audio_file)
    return audio_file, metadata
