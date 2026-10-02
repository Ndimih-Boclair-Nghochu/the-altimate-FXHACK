"""FastAPI application factory."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from fxbot import __version__
from fxbot.api.routers import health
from fxbot.config import Settings, get_settings

API_PREFIX = "/api"


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the API application. Uses the process-wide settings unless ``settings`` is given."""
    if settings is None:
        settings = get_settings()

    app = FastAPI(
        title="Altimate FX",
        version=__version__,
        docs_url=f"{API_PREFIX}/docs",
        redoc_url=None,
        openapi_url=f"{API_PREFIX}/openapi.json",
    )
    app.state.settings = settings

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )

    app.include_router(health.router, prefix=API_PREFIX)
    return app
