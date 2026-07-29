"""HTTP adapter for resumable run event streams."""

from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from sentinel_api.persistence.protocols import EventStore
from sentinel_api.realtime import ResumableEventStream, parse_last_event_id

router = APIRouter(tags=["runs"])


def event_store_from_app(request: Request) -> EventStore:
    """Resolve the store installed by the application's persistence lifespan."""

    store = getattr(request.app.state, "event_store", None)
    if store is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="event store is not configured",
        )
    return cast(EventStore, store)


@router.get("/runs/{run_id}/events", response_class=StreamingResponse)
async def stream_run_events(
    run_id: UUID,
    request: Request,
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
) -> StreamingResponse:
    """Replay events after Last-Event-ID and continue with live durable events."""

    try:
        cursor = parse_last_event_id(last_event_id)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(error),
        ) from error

    store = event_store_from_app(request)
    if await store.get_run(run_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run not found")

    stream = ResumableEventStream(store)
    return StreamingResponse(
        stream.iter_bytes(run_id, after_sequence=cursor),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )
