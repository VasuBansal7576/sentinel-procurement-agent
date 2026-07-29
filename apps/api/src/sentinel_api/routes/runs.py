"""Walking-skeleton run commands, queries, event delivery, and artifacts."""

from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response, status

from sentinel_api.application.walking_skeleton import (
    CreateRunRequest,
    InMemoryRunStore,
    RunView,
)
from sentinel_api.persistence.models import EventDraft, NewRun
from sentinel_api.persistence.protocols import EventStore

router = APIRouter(prefix="/runs", tags=["runs"])


@router.post("", response_model=RunView, status_code=status.HTTP_201_CREATED)
async def create_run(body: CreateRunRequest, request: Request) -> RunView:
    run_store = _run_store(request)
    run = run_store.create(body)
    event_store = _event_store(request)
    if event_store is not None:
        await event_store.create_run(
            NewRun(
                run_id=run.id,
                procurement_case_id=run.case_id,
                request_revision_id=run.request_revision_id,
                policy_revision=1,
                title=run.title,
                status=run.status.value,
                summary="Credential-free walking-skeleton run",
            )
        )
        for event in run.events[1:]:
            await event_store.append_event(
                run.id,
                EventDraft(
                    event_id=event.event_id,
                    event_type=event.event_type,
                    status=event.status,
                    summary=event.summary,
                    idempotency_key=event.event_type,
                ),
            )
    return run


@router.get("", response_model=tuple[RunView, ...])
async def list_runs(request: Request) -> tuple[RunView, ...]:
    return _run_store(request).list()


@router.get("/{run_id}", response_model=RunView)
async def get_run(run_id: UUID, request: Request) -> RunView:
    run = _run_store(request).get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@router.get("/{run_id}/artifacts/{artifact_id}")
async def download_artifact(run_id: UUID, artifact_id: UUID, request: Request) -> Response:
    artifact = _run_store(request).artifact(run_id, artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return Response(
        content=artifact.content,
        media_type=artifact.summary.media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{artifact.summary.filename}"',
            "X-Content-Type-Options": "nosniff",
        },
    )


def _run_store(request: Request) -> InMemoryRunStore:
    store = getattr(request.app.state, "run_store", None)
    if not isinstance(store, InMemoryRunStore):
        raise HTTPException(status_code=503, detail="Run store is not configured")
    return store


def _event_store(request: Request) -> EventStore | None:
    store = getattr(request.app.state, "event_store", None)
    return store if store is not None else None
