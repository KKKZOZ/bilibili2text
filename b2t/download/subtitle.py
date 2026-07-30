"""Fetch Bilibili native subtitles using the ``bili`` CLI."""

from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BilibiliSubtitle:
    """Subtitle text and optional timeline items returned by Bilibili."""

    text: str
    items: tuple[BilibiliSubtitleItem, ...] = ()


@dataclass(frozen=True)
class BilibiliSubtitleItem:
    """One timestamped Bilibili subtitle item."""

    start_ms: int
    end_ms: int
    text: str


def fetch_bilibili_subtitle(
    target: str, *, timeout_seconds: int = 60
) -> BilibiliSubtitle | None:
    """Return native Bilibili subtitle text when available.

    Missing subtitles, CLI failures, and malformed output are treated as cache misses so
    callers can fall back to ASR without failing the whole pipeline.
    """
    cleaned_target = target.strip()
    if not cleaned_target:
        return None

    cmd = ["bili", "video", cleaned_target, "--subtitle-timeline", "--json"]
    try:
        result = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except FileNotFoundError:
        logger.warning("bili CLI not found, falling back to ASR")
        return None
    except subprocess.TimeoutExpired:
        logger.warning("Fetching Bilibili subtitle timed out, falling back to ASR")
        return None
    except Exception as exc:  # noqa: BLE001
        logger.warning("Fetching Bilibili subtitle failed: %s", exc)
        return None

    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        logger.info("Bilibili subtitle unavailable, falling back to ASR: %s", detail)
        return None

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        logger.warning("Failed to parse Bilibili subtitle JSON: %s", exc)
        return None

    data = payload.get("data")
    if not isinstance(data, dict):
        logger.info("Bilibili subtitle is not available")
        return None

    subtitle = data.get("subtitle")
    if not isinstance(subtitle, dict) or not subtitle.get("available"):
        logger.info("Bilibili subtitle is not available")
        return None

    text = subtitle.get("text")
    if not isinstance(text, str) or not text.strip():
        logger.info("Bilibili subtitle is empty")
        return None

    items: list[BilibiliSubtitleItem] = []
    raw_items = subtitle.get("items")
    if isinstance(raw_items, list):
        for raw_item in raw_items:
            if not isinstance(raw_item, dict):
                continue

            item_text = raw_item.get("content")
            if not isinstance(item_text, str) or not item_text.strip():
                continue

            try:
                start_ms = max(0, round(float(raw_item.get("from", 0)) * 1000))
                end_ms = max(start_ms, round(float(raw_item.get("to", 0)) * 1000))
            except (TypeError, ValueError):
                continue

            items.append(
                BilibiliSubtitleItem(
                    start_ms=start_ms,
                    end_ms=end_ms,
                    text=item_text.strip(),
                )
            )

    return BilibiliSubtitle(text=text.strip(), items=tuple(items))
