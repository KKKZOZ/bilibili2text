"""Bounded background execution for API-triggered work."""

import atexit
from concurrent.futures import Future, ThreadPoolExecutor
from threading import BoundedSemaphore


class TaskQueueFull(RuntimeError):
    """Raised when a background queue has no worker or waiting capacity."""


class BoundedTaskQueue:
    """Thread pool with a bounded number of running and waiting tasks."""

    def __init__(
        self,
        *,
        max_workers: int,
        max_queued: int,
        thread_name_prefix: str,
    ) -> None:
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix=thread_name_prefix,
        )
        self._capacity = BoundedSemaphore(max_workers + max_queued)

    def submit(self, fn, /, *args, **kwargs) -> Future:
        if not self._capacity.acquire(blocking=False):
            raise TaskQueueFull("后台任务队列已满，请稍后重试")
        try:
            future = self._executor.submit(fn, *args, **kwargs)
        except Exception:
            self._capacity.release()
            raise
        future.add_done_callback(lambda _future: self._capacity.release())
        return future

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=False)


_main_queue = BoundedTaskQueue(
    max_workers=20,
    max_queued=40,
    thread_name_prefix="b2t-job",
)
_postprocess_queue = BoundedTaskQueue(
    max_workers=8,
    max_queued=16,
    thread_name_prefix="b2t-postprocess",
)


def submit_job(fn, /, *args, **kwargs) -> Future:
    return _main_queue.submit(fn, *args, **kwargs)


def submit_postprocess(fn, /, *args, **kwargs) -> Future:
    return _postprocess_queue.submit(fn, *args, **kwargs)


def shutdown_task_queues() -> None:
    _main_queue.shutdown()
    _postprocess_queue.shutdown()


atexit.register(shutdown_task_queues)
