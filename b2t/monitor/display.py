"""Immutable monitor status shared with terminal presenters."""

from dataclasses import dataclass


@dataclass(frozen=True)
class VideoStatus:
    bvid: str
    title: str
    published: str
    status: str


@dataclass(frozen=True)
class CreatorStatus:
    uid: int
    name: str
    interval: int
    status: str = "等待首次检查"
    checked_at: float | None = None
    next_check: float | None = None
    videos: tuple[VideoStatus, ...] = ()
    error: str = ""


@dataclass(frozen=True)
class MonitorSnapshot:
    creators: tuple[CreatorStatus, ...]
    checks: int = 0
    failed: int = 0
    activity: str = "正在启动监控"
