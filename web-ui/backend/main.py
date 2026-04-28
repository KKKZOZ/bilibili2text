"""FastAPI service for bilibili-to-text."""

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from b2t.converter.md_to_png import shutdown_png_renderer, warmup_png_renderer

from backend.logging_config import _configure_logging
from backend.routes.config_routes import router as config_router
from backend.routes.download import router as download_router
from backend.routes.health import router as health_router
from backend.routes.history import router as history_router
from backend.routes.process import router as process_router
from backend.routes.rag import router as rag_router
from backend.routes.runtime_routes import router as runtime_router
from backend.routes.summary import router as summary_router
from backend.task_queue import shutdown_task_queues

app = FastAPI(title="bilibili-to-text API", version="0.1.0")
logger = logging.getLogger(__name__)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    _configure_logging()
    try:
        warmup_png_renderer()
    except Exception as exc:  # noqa: BLE001
        logger.warning("PNG 渲染器预热失败，将在首次转换时重试: %s", exc)


@app.on_event("shutdown")
def on_shutdown() -> None:
    shutdown_task_queues()
    shutdown_png_renderer()


app.include_router(health_router)
app.include_router(runtime_router)
app.include_router(process_router)
app.include_router(config_router)
app.include_router(history_router)
app.include_router(download_router)
app.include_router(summary_router)
app.include_router(rag_router)
