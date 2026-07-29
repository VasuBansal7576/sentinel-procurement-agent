"""Resumable server-sent event delivery over the durable journal."""

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import asdict
from datetime import datetime
from enum import Enum
from typing import cast
from uuid import UUID

from sentinel_api.persistence.models import StoredEvent
from sentinel_api.persistence.protocols import EventStore

Waiter = Callable[[float], Awaitable[None]]


def _json_default(value: object) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Enum):
        return str(value.value)
    raise TypeError(f"cannot encode {type(value).__name__} in an SSE event")


def encode_event(event: StoredEvent) -> bytes:
    """Encode one journal row as a standards-compliant SSE message."""

    data = json.dumps(
        asdict(event),
        default=_json_default,
        separators=(",", ":"),
        sort_keys=True,
    )
    safe_type = event.event_type.replace("\r", "").replace("\n", "")
    return f"id: {event.sequence}\nevent: {safe_type}\ndata: {data}\n\n".encode()


class ResumableEventStream:
    """Poll the journal by durable sequence without a replay/live race."""

    def __init__(
        self,
        store: EventStore,
        *,
        batch_size: int = 250,
        poll_interval: float = 0.5,
        heartbeat_interval: float = 15.0,
        waiter: Waiter = asyncio.sleep,
    ) -> None:
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        if poll_interval <= 0:
            raise ValueError("poll_interval must be positive")
        if heartbeat_interval < poll_interval:
            raise ValueError("heartbeat_interval must not be shorter than poll_interval")
        self._store = store
        self._batch_size = batch_size
        self._poll_interval = poll_interval
        self._heartbeat_interval = heartbeat_interval
        self._wait = waiter

    async def iter_bytes(
        self,
        run_id: UUID,
        *,
        after_sequence: int = 0,
    ) -> AsyncIterator[bytes]:
        """Replay rows after the cursor, then continue polling for durable rows."""

        if after_sequence < 0:
            raise ValueError("after_sequence must not be negative")
        cursor = after_sequence
        idle_for = 0.0
        while True:
            events = await self._store.list_events(
                run_id,
                after_sequence=cursor,
                limit=self._batch_size,
            )
            if events:
                for event in events:
                    if event.sequence <= cursor:
                        raise RuntimeError("event store returned a non-monotonic sequence")
                    cursor = event.sequence
                    yield encode_event(event)
                idle_for = 0.0
                continue

            await self._wait(self._poll_interval)
            idle_for += self._poll_interval
            if idle_for >= self._heartbeat_interval:
                yield b": keep-alive\n\n"
                idle_for = 0.0


def parse_last_event_id(value: str | None) -> int:
    """Parse the standard reconnection cursor with a clear client error."""

    if value is None or value == "":
        return 0
    try:
        cursor = int(value)
    except ValueError as error:
        raise ValueError("Last-Event-ID must be a non-negative integer") from error
    if cursor < 0:
        raise ValueError("Last-Event-ID must be a non-negative integer")
    return cast(int, cursor)
