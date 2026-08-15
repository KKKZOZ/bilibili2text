"""Thread-safe change notifications for SSE consumers."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from threading import Lock

HEARTBEAT_SECONDS = 15.0


def job_channel(job_id: str) -> str:
    return f"job:{job_id}"


def history_channel(run_id: str) -> str:
    return f"history:{run_id}"


def _offer_notification(queue: asyncio.Queue[None]) -> None:
    if queue.empty():
        queue.put_nowait(None)


@dataclass(slots=True, eq=False)
class EventSubscription:
    _broker: EventBroker
    channels: tuple[str, ...]
    loop: asyncio.AbstractEventLoop
    queue: asyncio.Queue[None]
    _closed: bool = False

    async def wait(self) -> bool:
        try:
            await asyncio.wait_for(self.queue.get(), timeout=HEARTBEAT_SECONDS)
        except TimeoutError:
            return False
        return True

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._broker.unsubscribe(self)


class EventBroker:
    """Fan out coalesced change notifications across worker threads."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._subscriptions: dict[str, set[EventSubscription]] = defaultdict(set)

    def subscribe(self, channels: Iterable[str]) -> EventSubscription:
        normalized = tuple(dict.fromkeys(channels))
        subscription = EventSubscription(
            _broker=self,
            channels=normalized,
            loop=asyncio.get_running_loop(),
            queue=asyncio.Queue(maxsize=1),
        )
        with self._lock:
            for channel in normalized:
                self._subscriptions[channel].add(subscription)
        return subscription

    def unsubscribe(self, subscription: EventSubscription) -> None:
        with self._lock:
            for channel in subscription.channels:
                subscribers = self._subscriptions.get(channel)
                if subscribers is None:
                    continue
                subscribers.discard(subscription)
                if not subscribers:
                    del self._subscriptions[channel]

    def publish(self, channel: str) -> None:
        with self._lock:
            subscribers = tuple(self._subscriptions.get(channel, ()))
        for subscription in subscribers:
            if subscription._closed or subscription.loop.is_closed():
                continue
            try:
                subscription.loop.call_soon_threadsafe(
                    _offer_notification,
                    subscription.queue,
                )
            except RuntimeError:
                subscription.close()


event_broker = EventBroker()
