"""Walking-skeleton run commands, queries, event delivery, and artifacts."""

from collections.abc import Iterator
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Response, status
from fastapi.responses import StreamingResponse

from sentinel_api.application.walking_skeleton import (
    CreateRunRequest,
    InMemoryRunStore,
    RunView,
)

router = APIRouter(prefix="/runs", tags=["runs"])
store = InMemoryRunStore()


@router.post("", response_model=RunView, status_code=status.HTTP_201_CREATED)
async def create_run(request: CreateRunRequest) -> RunView:
    return store.create(request)


@router.get("", response_model=tuple[RunView, ...])
async def list_runs() -> tuple[RunView, ...]:
    return store.list()


@router.get("/{run_id}", response_model=RunView)
async def get_run(run_id: UUID) -> RunView:
    run = store.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@router.get("/{run_id}/events")
async def stream_events(
    run_id: UUID,
    last_event_id: int | None = Header(default=None, alias="Last-Event-ID"),
) -> StreamingResponse:
    events = store.events_after(run_id, last_event_id or 0)
    if events is None:
        raise HTTPException(status_code=404, detail="Run not found")

    def event_stream() -> Iterator[str]:
        for event in events:
            yield (
                f"id: {event.sequence}\n"
                f"event: {event.event_type}\n"
                f"data: {event.model_dump_json()}\n\n"
            )

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/{run_id}/artifacts/{artifact_id}")
async def download_artifact(run_id: UUID, artifact_id: UUID) -> Response:
    artifact = store.artifact(run_id, artifact_id)
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
