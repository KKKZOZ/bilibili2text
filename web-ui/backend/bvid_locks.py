"""In-memory convergence for active transcription jobs by BV ID."""

from __future__ import annotations

from dataclasses import dataclass
import time
from threading import Lock

from backend.settings import TRANSCRIPTION_BVID_LOCK_TIMEOUT_SECONDS


@dataclass(slots=True)
class BvidLockClaim:
    acquired: bool
    owner_job_id: str | None = None
    age_seconds: int = 0


@dataclass(slots=True)
class _BvidLockEntry:
    job_id: str
    monotonic_started_at: float


class BvidTranscriptionLocks:
    def __init__(self, *, timeout_seconds: int) -> None:
        self._timeout_seconds = max(1, int(timeout_seconds))
        self._entries: dict[str, _BvidLockEntry] = {}
        self._lock = Lock()

    def acquire(self, bvid: str, job_id: str) -> BvidLockClaim:
        normalized_bvid = bvid.strip()
        if not normalized_bvid:
            return BvidLockClaim(acquired=True)

        now = time.monotonic()
        with self._lock:
            entry = self._entries.get(normalized_bvid)
            if entry is not None:
                age_seconds = max(0, int(now - entry.monotonic_started_at))
                if age_seconds < self._timeout_seconds:
                    return BvidLockClaim(
                        acquired=False,
                        owner_job_id=entry.job_id,
                        age_seconds=age_seconds,
                    )

            self._entries[normalized_bvid] = _BvidLockEntry(
                job_id=job_id,
                monotonic_started_at=now,
            )
            return BvidLockClaim(acquired=True)

    def release(self, bvid: str, job_id: str) -> None:
        normalized_bvid = bvid.strip()
        if not normalized_bvid:
            return

        with self._lock:
            entry = self._entries.get(normalized_bvid)
            if entry is None or entry.job_id != job_id:
                return
            del self._entries[normalized_bvid]


bvid_transcription_locks = BvidTranscriptionLocks(
    timeout_seconds=TRANSCRIPTION_BVID_LOCK_TIMEOUT_SECONDS
)
