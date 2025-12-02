"""
FastAPI application entry point for the refactored backend.
"""

from __future__ import annotations

from fastapi import FastAPI

from backend.config import get_settings
from backend.routes import router


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Lumi Backend (FastAPI)", version="0.1.0")
    app.include_router(router, prefix=settings.api_prefix)
    return app


app = create_app()

