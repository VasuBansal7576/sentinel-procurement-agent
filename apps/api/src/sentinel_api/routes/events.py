"""HTTP adapter for resumable run event streams."""

from collections.abc import Iterator
from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from sentinel_api.application.walking_skeleton import InMemoryRunStore
from sentinel_api.persistence.protocols import EventStore
from sentinel_api.realtime import ResumableEventStream, encode_event, parse_last_event_id

router = APIRouter(tags=["runs"])


def event_store_from_app(request: Request) -> EventStore | None:
    """Resolve the store installed by the application's persistence lifespan."""

    store = getattr(request.app.state, "event_store", None)
    return cast(EventStore, store) if store is not None else None


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
    if store is None:
        memory_store = getattr(request.app.state, "run_store", None)
        if not isinstance(memory_store, InMemoryRunStore):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="event store is not configured",
            )
        events = memory_store.events_after(run_id, cursor)
        if events is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run not found")
        replay_events = events

        def finite_stream() -> Iterator[str]:
            for event in replay_events:
                yield (
                    f"id: {event.sequence}\n"
                    f"event: {event.event_type}\n"
                    f"data: {event.model_dump_json()}\n\n"
                )

        return StreamingResponse(
            finite_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "X-Accel-Buffering": "no",
            },
        )

    if await store.get_run(run_id) is None:
        memory_store = getattr(request.app.state, "run_store", None)
        if isinstance(memory_store, InMemoryRunStore):
            events = memory_store.events_after(run_id, cursor)
            if events is not None:
                replay_events = events

                def finite_stream() -> Iterator[str]:
                    for event in replay_events:
                        yield (
                            f"id: {event.sequence}\n"
                            f"event: {event.event_type}\n"
                            f"data: {event.model_dump_json()}\n\n"
                        )

                return StreamingResponse(
                    finite_stream(),
                    media_type="text/event-stream",
                    headers={
                        "Cache-Control": "no-cache, no-transform",
                        "X-Accel-Buffering": "no",
                    },
                )
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run not found")

    if getattr(store, "finite_streams", False):
        durable_events = await store.list_events(run_id, after_sequence=cursor)

        def finite_durable_stream() -> Iterator[bytes]:
            for event in durable_events:
                yield encode_event(event)

        return StreamingResponse(
            finite_durable_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "X-Accel-Buffering": "no",
            },
        )

    stream = ResumableEventStream(store)
    return StreamingResponse(
        stream.iter_bytes(run_id, after_sequence=cursor),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )
