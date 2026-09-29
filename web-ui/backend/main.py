"""FastAPI service for bilibili-to-text."""

import logging

from fastapi import FastAPI

from b2t.converter.md_to_png import shutdown_png_renderer, warmup_png_renderer
from backend.cors import configure_cors
from backend.ephemeral_uploads import (
    start_ephemeral_upload_cleanup,
    stop_ephemeral_upload_cleanup,
)
from backend.logging_config import _configure_logging
from backend.routes.config_routes import router as config_router
from backend.routes.download import router as download_router
from backend.routes.health import router as health_router
from backend.routes.history import router as history_router
from backend.routes.process import router as process_router
from backend.routes.rag import router as rag_router
from backend.routes.report import router as report_router
from backend.routes.runtime_routes import router as runtime_router
from backend.routes.summary import router as summary_router
from backend.task_queue import shutdown_task_queues

app = FastAPI(title="bilibili-to-text API", version="0.1.0")
logger = logging.getLogger(__name__)

configure_cors(app)


@app.on_event("startup")
def on_startup() -> None:
    _configure_logging()
    start_ephemeral_upload_cleanup()
    try:
        warmup_png_renderer()
    except Exception as exc:
        logger.warning("PNG 渲染器预热失败，将在首次转换时重试: %s", exc)


@app.on_event("shutdown")
def on_shutdown() -> None:
    stop_ephemeral_upload_cleanup()
    shutdown_task_queues()
    shutdown_png_renderer()


app.include_router(health_router)
app.include_router(runtime_router)
app.include_router(process_router)
app.include_router(config_router)
app.include_router(history_router)
app.include_router(download_router)
app.include_router(summary_router)
app.include_router(report_router)
app.include_router(rag_router)
