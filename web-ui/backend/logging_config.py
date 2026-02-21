"""Logging infrastructure: redaction, filters, job log handler, and configuration."""

import logging
import re

from backend.jobs import _append_job_log

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
JOB_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
JOB_LOG_DATE_FORMAT = "%H:%M:%S"

_URL_PATTERN = re.compile(r"https?://[^\s\"']+")
_OSS_OBJECT_KEY_PATTERN = re.compile(r"(temp-audio/)[^\s\"']+")
_SECRET_PATTERN = re.compile(
    r"(?i)\b(access[_-]?key(?:[_-]?(?:id|secret))?|api[_-]?key|token|secret)\b\s*[:=]\s*[^,\s]+"
)


def _redact_text(message: str) -> str:
    sanitized = _URL_PATTERN.sub("[REDACTED_URL]", message)
    sanitized = _OSS_OBJECT_KEY_PATTERN.sub(r"\1[REDACTED_OBJECT_KEY]", sanitized)
    sanitized = _SECRET_PATTERN.sub(r"\1=[REDACTED]", sanitized)
    return sanitized


class _SensitiveDataFilter(logging.Filter):
    """在日志输出前统一脱敏，确保日志源头就是安全内容。"""

    def filter(self, record: logging.LogRecord) -> bool:
        original = record.getMessage()
        sanitized = _redact_text(original)
        if sanitized != original:
            record.msg = sanitized
            record.args = ()
        return True


_SENSITIVE_DATA_FILTER = _SensitiveDataFilter()


class _JobLogHandler(logging.Handler):
    def __init__(self, job_id: str, thread_id: int) -> None:
        super().__init__(level=logging.INFO)
        self._job_id = job_id
        self._thread_id = thread_id
        self.setFormatter(
            logging.Formatter(fmt=JOB_LOG_FORMAT, datefmt=JOB_LOG_DATE_FORMAT)
        )
        self.addFilter(_SENSITIVE_DATA_FILTER)

    def emit(self, record: logging.LogRecord) -> None:
        if record.thread != self._thread_id:
            return

        logger_name = record.name
        if not (
            logger_name == "b2t"
            or logger_name.startswith("b2t.")
            or logger_name in {"dashscope", "httpx"}
        ):
            return

        try:
            line = self.format(record)
        except Exception:
            self.handleError(record)
            return

        _append_job_log(self._job_id, line)


def _configure_logging() -> None:
    """统一后端日志格式，包含到秒级时间戳。"""
    formatter = logging.Formatter(fmt=LOG_FORMAT, datefmt=LOG_DATE_FORMAT)
    for logger_name in ("", "uvicorn", "uvicorn.error", "uvicorn.access"):
        target_logger = logging.getLogger(logger_name)
        for handler in target_logger.handlers:
            handler.setFormatter(formatter)
            if not any(
                isinstance(filter_obj, _SensitiveDataFilter)
                for filter_obj in handler.filters
            ):
                handler.addFilter(_SENSITIVE_DATA_FILTER)

    # 任务日志面板依赖 INFO 级别日志；这些 logger 默认可能继承到 WARNING。
    logging.getLogger("b2t").setLevel(logging.INFO)
    logging.getLogger("dashscope").setLevel(logging.INFO)
    logging.getLogger("httpx").setLevel(logging.INFO)
