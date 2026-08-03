"""Cooperative cancellation primitives shared by pipeline callers."""

from __future__ import annotations

from collections.abc import Callable
from threading import Event, RLock
from typing import TypeVar

_T = TypeVar("_T")


class PipelineCancelled(Exception):
    """Raised when a caller requests cooperative pipeline cancellation."""


class CancellationToken:
    """A thread-safe cancellation signal for one unit of work."""

    def __init__(self) -> None:
        self._event = Event()
        self._phase_lock = RLock()

    def cancel(self) -> None:
        with self._phase_lock:
            self._event.set()

    def is_cancelled(self) -> bool:
        return self._event.is_set()

    def raise_if_cancelled(self) -> None:
        if self.is_cancelled():
            raise PipelineCancelled("任务已被用户取消")

    def run_if_active(self, action: Callable[[], _T]) -> _T:
        """Run one stage atomically with respect to cancellation."""
        with self._phase_lock:
            self.raise_if_cancelled()
            return action()

    def cancel_if(
        self, action: Callable[[], tuple[bool, str | None]]
    ) -> tuple[bool, str | None]:
        """Set cancellation only when the guarded state transition succeeds."""
        with self._phase_lock:
            result = action()
            if result[0]:
                self._event.set()
            return result
