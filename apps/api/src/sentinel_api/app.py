"""FastAPI application factory."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from sentinel_api.config import get_settings
from sentinel_api.routes.health import router as health_router
from sentinel_api.routes.runs import router as runs_router


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Sentinel API",
        version="0.1.0",
        docs_url="/api/docs" if settings.environment != "production" else None,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[str(settings.web_origin)],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health_router, prefix="/api")
    app.include_router(runs_router, prefix="/api")
    return app
