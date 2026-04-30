"""Bounded background execution for API-triggered work."""

from concurrent.futures import Future, ThreadPoolExecutor
import atexit

_main_executor = ThreadPoolExecutor(max_workers=20, thread_name_prefix="b2t-job")
_postprocess_executor = ThreadPoolExecutor(
    max_workers=8,
    thread_name_prefix="b2t-postprocess",
)


def submit_job(fn, /, *args, **kwargs) -> Future:
    return _main_executor.submit(fn, *args, **kwargs)


def submit_postprocess(fn, /, *args, **kwargs) -> Future:
    return _postprocess_executor.submit(fn, *args, **kwargs)


def shutdown_task_queues() -> None:
    _main_executor.shutdown(wait=False, cancel_futures=False)
    _postprocess_executor.shutdown(wait=False, cancel_futures=False)


atexit.register(shutdown_task_queues)
