"""Unit tests for durable SSE resume behavior."""

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from sentinel_api.persistence.models import StoredEvent
from sentinel_api.realtime import ResumableEventStream, encode_event, parse_last_event_id


def _event(run_id: UUID, sequence: int) -> StoredEvent:
    return StoredEvent(
        event_id=uuid4(),
        run_id=run_id,
        sequence=sequence,
        parent_run_id=None,
        work_item_id=None,
        actor_id="worker",
        event_type="tool.completed",
        status="completed",
        causation_id=None,
        correlation_id=None,
        idempotency_key=None,
        summary=f"Completed event {sequence}",
        payload={"sequence": sequence},
        payload_ref=None,
        created_at=datetime(2026, 7, 29, 12, sequence, tzinfo=UTC),
    )


class ReplayStore:
    def __init__(self, events: Sequence[StoredEvent]) -> None:
        self.events = events
        self.cursors: list[int] = []

    async def list_events(
        self,
        run_id: UUID,
        *,
        after_sequence: int = 0,
        limit: int = 500,
    ) -> Sequence[StoredEvent]:
        self.cursors.append(after_sequence)
        return tuple(
            event
            for event in self.events
            if event.run_id == run_id and event.sequence > after_sequence
        )[:limit]


def test_encode_event_uses_sequence_as_sse_id_and_json_envelope() -> None:
    run_id = uuid4()
    encoded = encode_event(_event(run_id, 7)).decode()

    assert encoded.startswith("id: 7\nevent: tool.completed\ndata: ")
    payload = json.loads(encoded.split("data: ", 1)[1])
    assert payload["run_id"] == str(run_id)
    assert payload["sequence"] == 7
    assert encoded.endswith("\n\n")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(None, 0), ("", 0), ("0", 0), ("42", 42)],
)
def test_parse_last_event_id(raw: str | None, expected: int) -> None:
    assert parse_last_event_id(raw) == expected


@pytest.mark.parametrize("raw", ["-1", "1.5", "not-a-cursor"])
def test_parse_last_event_id_rejects_invalid_cursor(raw: str) -> None:
    with pytest.raises(ValueError, match="non-negative integer"):
        parse_last_event_id(raw)


@pytest.mark.asyncio
async def test_resume_replays_strictly_after_cursor_in_order() -> None:
    run_id = uuid4()
    store = ReplayStore([_event(run_id, 1), _event(run_id, 2), _event(run_id, 3)])
    stream = ResumableEventStream(store)  # type: ignore[arg-type]
    iterator = stream.iter_bytes(run_id, after_sequence=1)

    second = await anext(iterator)
    third = await anext(iterator)
    await iterator.aclose()

    assert second.startswith(b"id: 2\n")
    assert third.startswith(b"id: 3\n")
    assert store.cursors == [1]


@pytest.mark.asyncio
async def test_stream_emits_heartbeat_without_advancing_cursor() -> None:
    run_id = uuid4()
    store = ReplayStore([])

    async def no_wait(_: float) -> None:
        return None

    stream = ResumableEventStream(
        store,  # type: ignore[arg-type]
        poll_interval=0.5,
        heartbeat_interval=0.5,
        waiter=no_wait,
    )
    iterator = stream.iter_bytes(run_id, after_sequence=9)

    assert await anext(iterator) == b": keep-alive\n\n"
    await iterator.aclose()
    assert store.cursors == [9]
