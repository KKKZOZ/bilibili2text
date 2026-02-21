"""FastAPI service for bilibili-to-text."""

# state must be imported first to ensure sys.path is configured for b2t imports.
from backend import state as _state  # noqa: F401

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.logging_config import _configure_logging
from backend.routes.config_routes import router as config_router
from backend.routes.download import router as download_router
from backend.routes.health import router as health_router
from backend.routes.history import router as history_router
from backend.routes.process import router as process_router

app = FastAPI(title="bilibili-to-text API", version="0.1.0")

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


app.include_router(health_router)
app.include_router(process_router)
app.include_router(config_router)
app.include_router(history_router)
app.include_router(download_router)
