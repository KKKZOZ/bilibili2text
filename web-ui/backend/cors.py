"""CORS configuration for separately hosted frontends."""

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.settings import get_app_config


def configure_cors(app: FastAPI) -> None:
    configured = get_app_config().backend.cors_origins
    # Preserve explicit environment overrides for existing deployments.
    origins = os.environ.get("B2T_CORS_ORIGINS", ",".join(configured))
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
