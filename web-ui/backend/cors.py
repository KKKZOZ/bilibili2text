"""CORS configuration for separately hosted frontends."""

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

DEFAULT_ORIGINS = (
    "http://localhost:5173,http://127.0.0.1:5173,"
    "http://localhost:6010,http://127.0.0.1:6010"
)


def configure_cors(app: FastAPI) -> None:
    origins = os.environ.get("B2T_CORS_ORIGINS", DEFAULT_ORIGINS)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            origin.strip().rstrip("/")
            for origin in origins.split(",")
            if origin.strip()
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
