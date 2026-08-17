import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "web-ui"))

from backend.logging_config import _configure_logging


def test_configure_logging_keeps_progress_info_and_suppresses_http_requests() -> None:
    logger_names = ("b2t", "dashscope", "httpx")
    original_levels = {
        logger_name: logging.getLogger(logger_name).level
        for logger_name in logger_names
    }

    try:
        _configure_logging()

        assert logging.getLogger("b2t").level == logging.INFO
        assert logging.getLogger("dashscope").level == logging.INFO
        assert logging.getLogger("httpx").level == logging.WARNING
        assert logging.getLogger("b2t.download.yutto_api").isEnabledFor(logging.INFO)
        assert not logging.getLogger("httpx").isEnabledFor(logging.INFO)
    finally:
        for logger_name, level in original_levels.items():
            logging.getLogger(logger_name).setLevel(level)
