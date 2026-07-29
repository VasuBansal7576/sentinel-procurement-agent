"""Real PostgreSQL tests for atomic journal and projection guarantees."""

import asyncio
import os
from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
import pytest_asyncio
from psycopg import AsyncConnection
from psycopg.errors import RaiseException

from sentinel_api.persistence.models import EventDraft, NewRun
from sentinel_api.persistence.postgres import (
    InvalidProjectionEventError,
    PostgresEventStore,
)

pytestmark = pytest.mark.asyncio


def _test_database_url() -> str:
    value = os.getenv("SENTINEL_TEST_DATABASE_URL")
    if value is None:
        pytest.skip("set SENTINEL_TEST_DATABASE_URL to run PostgreSQL integration tests")
    return value.replace("postgresql+psycopg://", "postgresql://", 1)


@pytest_asyncio.fixture
async def store() -> AsyncIterator[PostgresEventStore]:
    database_url = _test_database_url()
    connection = await AsyncConnection.connect(database_url)
    await connection.execute("DROP SCHEMA IF EXISTS sentinel CASCADE")
    await connection.commit()
    await connection.close()

    event_store = PostgresEventStore.from_url(database_url, max_size=20)
    await event_store.open()
    assert await event_store.migrate() == ("0001", "0002", "0003", "0004", "0005")
    assert await event_store.migrate() == ()
    try:
        yield event_store
    finally:
        await event_store.close()


async def test_append_is_atomic_ordered_and_idempotent(
    store: PostgresEventStore,
) -> None:
    run = NewRun(title="Source packaging suppliers")
    created = await store.create_run(run)
    draft = EventDraft(
        event_type="run.status_changed",
        status="running",
        summary="Research started",
        payload={"status": "running", "active_phase": "research"},
        idempotency_key="workflow-started",
    )

    first = await store.append_event(run.run_id, draft)
    duplicate = await store.append_event(run.run_id, draft)

    assert created.sequence == 1
    assert first.sequence == 2
    assert duplicate.event_id == first.event_id
    assert [event.sequence for event in await store.list_events(run.run_id)] == [1, 2]
    summary = await store.get_run(run.run_id)
    assert summary is not None
    assert summary.status == "running"
    assert summary.active_phase == "research"
    assert summary.event_count == 2

    messages = await store.claim_outbox(consumer_id="projection-publisher")
    assert [(message.sequence, message.attempts) for message in messages] == [(1, 1), (2, 1)]
    assert (
        await store.mark_outbox_published(
            outbox_id=messages[0].outbox_id,
            consumer_id="other-consumer",
        )
        is False
    )
    assert await store.mark_outbox_published(
        outbox_id=messages[0].outbox_id,
        consumer_id="projection-publisher",
    )


async def test_concurrent_appends_allocate_gap_free_per_run_sequences(
    store: PostgresEventStore,
) -> None:
    run = NewRun(title="Concurrent journal")
    await store.create_run(run)

    appended = await asyncio.gather(
        *(
            store.append_event(
                run.run_id,
                EventDraft(
                    event_type="tool.completed",
                    status="completed",
                    summary=f"Completed tool {index}",
                    payload={"index": index},
                ),
            )
            for index in range(24)
        )
    )

    assert sorted(event.sequence for event in appended) == list(range(2, 26))
    events = await store.list_events(run.run_id)
    assert [event.sequence for event in events] == list(range(1, 26))


async def test_projection_rebuild_restores_run_work_and_subagent_views(
    store: PostgresEventStore,
) -> None:
    run = NewRun(title="Projection replay")
    await store.create_run(run)
    work_item_id = uuid4()
    subagent_id = uuid4()
    await store.append_event(
        run.run_id,
        EventDraft(
            event_type="subagent.started",
            status="running",
            summary="Supplier verification started",
            payload={
                "subagent_id": str(subagent_id),
                "label": "Supplier verification",
                "goal": "Verify company identity",
                "status": "running",
                "tool_scope": ["search.query", "browser.read"],
            },
        ),
    )
    await store.append_event(
        run.run_id,
        EventDraft(
            event_type="work.planned",
            status="queued",
            summary="Planned identity check",
            work_item_id=work_item_id,
            payload={
                "phase": "research",
                "kind": "supplier_verification",
                "label": "Verify supplier identity",
                "status": "queued",
                "position": 1,
                "subagent_id": str(subagent_id),
            },
        ),
    )
    await store.append_event(
        run.run_id,
        EventDraft(
            event_type="work.completed",
            status="completed",
            summary="Supplier identity verified",
            work_item_id=work_item_id,
            payload={"completed_units": 1, "total_units": 1},
        ),
    )
    await store.append_event(
        run.run_id,
        EventDraft(
            event_type="subagent.completed",
            status="completed",
            summary="Verification child completed",
            payload={
                "subagent_id": str(subagent_id),
                "completed_at": "2026-07-29T12:00:00+00:00",
            },
        ),
    )

    before = await store.get_run(run.run_id)
    rebuilt = await store.rebuild_projections(run.run_id)
    work_items = await store.list_work_items(run.run_id)
    subagents = await store.list_subagents(run.run_id)

    assert before == rebuilt
    assert rebuilt.completed_work_items == 1
    assert rebuilt.total_work_items == 1
    assert rebuilt.active_subagents == 0
    assert work_items[0].status == "completed"
    assert work_items[0].subagent_id == subagent_id
    assert subagents[0].status == "completed"
    assert subagents[0].tool_scope == ("search.query", "browser.read")


async def test_invalid_projection_event_rolls_back_event_outbox_and_sequence(
    store: PostgresEventStore,
) -> None:
    run = NewRun(title="Atomic projection failure")
    await store.create_run(run)

    with pytest.raises(InvalidProjectionEventError):
        await store.append_event(
            run.run_id,
            EventDraft(
                event_type="work.started",
                status="running",
                summary="Malformed first work event",
                work_item_id=uuid4(),
            ),
        )

    valid = await store.append_event(
        run.run_id,
        EventDraft(
            event_type="run.status_changed",
            status="running",
            summary="Run started",
            payload={"status": "running"},
        ),
    )
    assert valid.sequence == 2
    assert len(await store.claim_outbox(consumer_id="after-rollback")) == 2


async def test_journal_rows_cannot_be_updated_or_deleted(
    store: PostgresEventStore,
) -> None:
    run = NewRun(title="Immutable journal")
    created = await store.create_run(run)
    connection = await AsyncConnection.connect(_test_database_url())
    try:
        with pytest.raises(RaiseException, match="append-only"):
            async with connection.transaction():
                await connection.execute(
                    "UPDATE sentinel.run_events SET summary = 'rewritten' WHERE event_id = %s",
                    (created.event_id,),
                )
        with pytest.raises(RaiseException, match="append-only"):
            async with connection.transaction():
                await connection.execute(
                    "DELETE FROM sentinel.run_events WHERE event_id = %s",
                    (created.event_id,),
                )
    finally:
        await connection.close()


async def test_session_history_reads_current_projection_without_replay(
    store: PostgresEventStore,
) -> None:
    older = NewRun(title="Older session")
    newer = NewRun(title="Newer session")
    await store.create_run(older)
    await store.create_run(newer)
    await store.append_event(
        older.run_id,
        EventDraft(
            event_type="run.status_changed",
            status="paused",
            summary="Paused by operator",
            payload={"status": "paused", "summary": "Waiting for budget"},
        ),
    )

    history = await store.list_sessions()

    assert [session.run_id for session in history[:2]] == [older.run_id, newer.run_id]
    assert history[0].summary == "Waiting for budget"
