"""FastAPI application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from sentinel_api.application.walking_skeleton import InMemoryRunStore
from sentinel_api.config import Settings, get_settings
from sentinel_api.email import InMemoryEmailExecutionStore, PostgresEmailExecutionStore
from sentinel_api.integration.demo import DemoProfile
from sentinel_api.integration.event_store import InMemoryEventStore
from sentinel_api.integration.executor import CredentialFreeWorkExecutor
from sentinel_api.integration.protected import ProtectedEmailBoundary, build_email_provider
from sentinel_api.integration.repository import (
    InMemoryIntegrationRepository,
    PostgresIntegrationRepository,
)
from sentinel_api.integration.runtime import InlineRuntimeLauncher, LazyTemporalRuntimeLauncher
from sentinel_api.integration.service import IntegrationService
from sentinel_api.persistence.runtime import event_store_runtime
from sentinel_api.protected_actions import ApprovalBroker, PostgresApprovalBroker
from sentinel_api.research.agent_reach import AgentReachResearchClient, FakeResearchClient
from sentinel_api.routes.events import router as events_router
from sentinel_api.routes.health import router as health_router
from sentinel_api.routes.operator import router as operator_router
from sentinel_api.routes.runs import router as runs_router
from sentinel_api.workflows.activities import RuntimeActivities


def _controlled_recipient(settings: Settings) -> str:
    return settings.controlled_recipient or "procurement-demo@example.test"


def _research_client(settings: Settings) -> FakeResearchClient | AgentReachResearchClient:
    if settings.research_provider == "agent_reach":
        return AgentReachResearchClient()
    return FakeResearchClient()


def _honesty_banner(settings: Settings) -> str:
    if settings.research_provider == "agent_reach":
        return (
            "Live public-web research via Agent Reach backends "
            "(Exa search + Jina Reader). Source URLs are real pages. "
            "Approval records permission only and never sends."
        )
    return (
        "Deterministic local research fixtures · not live market data · "
        "approval records permission only and never sends"
    )


def _runtime_disclosure(settings: Settings, demo_profile: DemoProfile) -> str:
    parts: list[str] = []
    if settings.research_provider == "agent_reach":
        parts.append(
            "Research uses Agent Reach-style public search/read (mcporter Exa + Jina Reader)."
        )
    else:
        parts.append(demo_profile.disclosure)
    if settings.email_provider == "resend" and settings.credential_gate == "live-approved":
        parts.append(
            "Live Resend email enabled for one controlled recipient; "
            "execute is a separate operator action."
        )
    return " ".join(parts)


def _build_executor(
    *,
    settings: Settings,
    records: object,
    event_store: object,
    proposal_broker: object,
    demo_profile: DemoProfile,
    recipient: str,
) -> CredentialFreeWorkExecutor:
    return CredentialFreeWorkExecutor(
        records=records,  # type: ignore[arg-type]
        event_store=event_store,  # type: ignore[arg-type]
        proposal_broker=proposal_broker,  # type: ignore[arg-type]
        demo_profile=demo_profile,
        controlled_recipient=recipient,
        research_client=_research_client(settings),
        research_mode=settings.research_provider,
    )


def _build_email_boundary(
    *,
    settings: Settings,
    broker: object,
    store: object,
) -> ProtectedEmailBoundary:
    return ProtectedEmailBoundary(
        broker=broker,  # type: ignore[arg-type]
        store=store,  # type: ignore[arg-type]
        provider=build_email_provider(settings),
        sender=settings.email_sender,
        controlled_recipient=_controlled_recipient(settings),
        live_dispatch_enabled=(
            settings.email_provider == "resend" and settings.credential_gate == "live-approved"
        ),
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    demo_profile = DemoProfile.from_settings(settings)
    if settings.persistence_mode == "memory":
        yield
        return
    async with event_store_runtime(
        settings.database_url,
        migrate=settings.auto_migrate,
    ) as event_store:
        app.state.event_store = event_store
        app.state.approval_broker = PostgresApprovalBroker(event_store.connection_pool)
        records = PostgresIntegrationRepository(event_store.connection_pool)
        recipient = _controlled_recipient(settings)
        executor = _build_executor(
            settings=settings,
            records=records,
            event_store=event_store,
            proposal_broker=app.state.approval_broker,
            demo_profile=demo_profile,
            recipient=recipient,
        )
        activities = RuntimeActivities(event_store, executor)
        email_store = PostgresEmailExecutionStore(event_store.connection_pool)
        email_boundary = _build_email_boundary(
            settings=settings,
            broker=app.state.approval_broker,
            store=email_store,
        )
        app.state.integration_service = IntegrationService(
            event_store=event_store,
            records=records,
            runtime=LazyTemporalRuntimeLauncher(
                address=settings.temporal_address,
                namespace=settings.temporal_namespace,
                task_queue="sentinel-procurement",
            ),
            proposal_broker=app.state.approval_broker,
            runtime_disclosure=_runtime_disclosure(settings, demo_profile),
            honesty_banner=_honesty_banner(settings),
            controlled_recipient=recipient,
            email_boundary=email_boundary,
            live_email_enabled=email_boundary.live_dispatch_enabled,
        )
        app.state.runtime_activities = activities
        app.state.email_execution_store = email_store
        app.state.email_boundary = email_boundary
        yield


def create_app() -> FastAPI:
    settings = get_settings()
    demo_profile = DemoProfile.from_settings(settings)
    app = FastAPI(
        title="Sentinel API",
        version="0.1.0",
        docs_url="/api/docs" if settings.environment != "production" else None,
        lifespan=lifespan,
    )
    app.state.run_store = InMemoryRunStore()
    app.state.approval_broker = ApprovalBroker()
    memory_events = InMemoryEventStore()
    memory_records = InMemoryIntegrationRepository()
    recipient = _controlled_recipient(settings)
    executor = _build_executor(
        settings=settings,
        records=memory_records,
        event_store=memory_events,
        proposal_broker=app.state.approval_broker,
        demo_profile=demo_profile,
        recipient=recipient,
    )
    activities = RuntimeActivities(memory_events, executor)
    email_store = InMemoryEmailExecutionStore()
    email_boundary = _build_email_boundary(
        settings=settings,
        broker=app.state.approval_broker,
        store=email_store,
    )
    app.state.event_store = memory_events
    app.state.integration_service = IntegrationService(
        event_store=memory_events,
        records=memory_records,
        runtime=InlineRuntimeLauncher(
            event_store=memory_events,
            activities=activities,
        ),
        proposal_broker=app.state.approval_broker,
        runtime_disclosure=_runtime_disclosure(settings, demo_profile),
        honesty_banner=_honesty_banner(settings),
        controlled_recipient=recipient,
        email_boundary=email_boundary,
        live_email_enabled=email_boundary.live_dispatch_enabled,
    )
    app.state.runtime_activities = activities
    app.state.email_execution_store = email_store
    app.state.email_boundary = email_boundary
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
    app.include_router(operator_router, prefix="/api")
    return app
