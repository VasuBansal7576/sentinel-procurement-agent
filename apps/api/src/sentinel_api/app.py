"""FastAPI application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from sentinel_api.application.walking_skeleton import InMemoryRunStore
from sentinel_api.config import get_settings
from sentinel_api.email import InMemoryEmailExecutionStore, PostgresEmailExecutionStore
from sentinel_api.persistence.runtime import event_store_runtime
from sentinel_api.protected_actions import ApprovalBroker, PostgresApprovalBroker
from sentinel_api.routes.events import router as events_router
from sentinel_api.routes.health import router as health_router
from sentinel_api.routes.runs import router as runs_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    if settings.persistence_mode == "memory":
        yield
        return
    async with event_store_runtime(
        settings.database_url,
        migrate=settings.auto_migrate,
    ) as event_store:
        app.state.event_store = event_store
        app.state.approval_broker = PostgresApprovalBroker(event_store.connection_pool)
        app.state.email_execution_store = PostgresEmailExecutionStore(event_store.connection_pool)
        yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Sentinel API",
        version="0.1.0",
        docs_url="/api/docs" if settings.environment != "production" else None,
        lifespan=lifespan,
    )
    app.state.run_store = InMemoryRunStore()
    app.state.approval_broker = ApprovalBroker()
    app.state.email_execution_store = InMemoryEmailExecutionStore()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[str(settings.web_origin)],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health_router, prefix="/api")
    app.include_router(runs_router, prefix="/api")
    app.include_router(events_router, prefix="/api")
    return app
