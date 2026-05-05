from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "web-ui"))

from backend.bvid_locks import BvidTranscriptionLocks


def test_bvid_lock_rejects_concurrent_claim_before_timeout() -> None:
    locks = BvidTranscriptionLocks(timeout_seconds=600)

    first = locks.acquire("BV1R9i4BoE7H", "job-a")
    second = locks.acquire("BV1R9i4BoE7H", "job-b")

    assert first.acquired is True
    assert second.acquired is False
    assert second.owner_job_id == "job-a"


def test_bvid_lock_allows_reclaim_after_timeout() -> None:
    locks = BvidTranscriptionLocks(timeout_seconds=1)

    first = locks.acquire("BV1R9i4BoE7H", "job-a")
    time.sleep(1.05)
    second = locks.acquire("BV1R9i4BoE7H", "job-b")

    assert first.acquired is True
    assert second.acquired is True


def test_bvid_lock_release_only_removes_owner_claim() -> None:
    locks = BvidTranscriptionLocks(timeout_seconds=600)

    locks.acquire("BV1R9i4BoE7H", "job-a")
    locks.release("BV1R9i4BoE7H", "job-b")
    still_blocked = locks.acquire("BV1R9i4BoE7H", "job-c")
    locks.release("BV1R9i4BoE7H", "job-a")
    after_release = locks.acquire("BV1R9i4BoE7H", "job-d")

    assert still_blocked.acquired is False
    assert after_release.acquired is True
