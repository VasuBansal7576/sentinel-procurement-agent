"""PostgreSQL implementation of the durable event store."""

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import cast
from uuid import UUID

from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from sentinel_api.persistence.migrations import apply_migrations
from sentinel_api.persistence.models import (
    EventDraft,
    JsonObject,
    NewRun,
    OutboxMessage,
    RunSummary,
    StoredEvent,
    SubagentProjection,
    WorkItemProjection,
)

Row = dict[str, object]


class RunNotFoundError(LookupError):
    """Raised when a command references an unknown run."""


class InvalidProjectionEventError(ValueError):
    """Raised when an event cannot deterministically update its projection."""


def _uuid(value: object) -> UUID:
    if isinstance(value, UUID):
        return value
    return UUID(str(value))


def _optional_uuid(value: object) -> UUID | None:
    return None if value is None else _uuid(value)


def _datetime(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"expected datetime, got {type(value).__name__}")
    return value


def _optional_datetime(value: object) -> datetime | None:
    return None if value is None else _datetime(value)


def _json_object(value: object) -> JsonObject:
    if not isinstance(value, Mapping):
        raise TypeError(f"expected JSON object, got {type(value).__name__}")
    return cast(JsonObject, value)


def _stored_event(row: Mapping[str, object]) -> StoredEvent:
    return StoredEvent(
        event_id=_uuid(row["event_id"]),
        run_id=_uuid(row["run_id"]),
        sequence=int(cast(int, row["per_run_sequence"])),
        parent_run_id=_optional_uuid(row["parent_run_id"]),
        work_item_id=_optional_uuid(row["work_item_id"]),
        actor_id=cast(str | None, row["actor_id"]),
        event_type=str(row["event_type"]),
        status=str(row["status"]),
        causation_id=_optional_uuid(row["causation_id"]),
        correlation_id=_optional_uuid(row["correlation_id"]),
        idempotency_key=cast(str | None, row["idempotency_key"]),
        summary=str(row["summary"]),
        payload=_json_object(row["payload"]),
        payload_ref=cast(str | None, row["payload_ref"]),
        created_at=_datetime(row["created_at"]),
    )


def _run_summary(row: Mapping[str, object]) -> RunSummary:
    return RunSummary(
        run_id=_uuid(row["run_id"]),
        parent_run_id=_optional_uuid(row["parent_run_id"]),
        title=str(row["title"]),
        status=str(row["status"]),
        summary=cast(str | None, row["summary"]),
        active_phase=cast(str | None, row["active_phase"]),
        request_revision_id=_optional_uuid(row["request_revision_id"]),
        policy_revision=cast(int | None, row["policy_revision"]),
        completed_work_items=int(cast(int, row["completed_work_items"])),
        total_work_items=int(cast(int, row["total_work_items"])),
        active_subagents=int(cast(int, row["active_subagents"])),
        blocker_count=int(cast(int, row["blocker_count"])),
        event_count=int(cast(int, row["event_count"])),
        last_sequence=int(cast(int, row["last_sequence"])),
        started_at=_optional_datetime(row["started_at"]),
        completed_at=_optional_datetime(row["completed_at"]),
        created_at=_datetime(row["created_at"]),
        updated_at=_datetime(row["updated_at"]),
    )


def _work_item(row: Mapping[str, object]) -> WorkItemProjection:
    return WorkItemProjection(
        run_id=_uuid(row["run_id"]),
        work_item_id=_uuid(row["work_item_id"]),
        parent_work_item_id=_optional_uuid(row["parent_work_item_id"]),
        subagent_id=_optional_uuid(row["subagent_id"]),
        phase=str(row["phase"]),
        kind=str(row["kind"]),
        label=str(row["label"]),
        status=str(row["status"]),
        position=int(cast(int, row["position"])),
        completed_units=cast(int | None, row["completed_units"]),
        total_units=cast(int | None, row["total_units"]),
        blocker=cast(str | None, row["blocker"]),
        last_sequence=int(cast(int, row["last_sequence"])),
        created_at=_datetime(row["created_at"]),
        updated_at=_datetime(row["updated_at"]),
    )


def _subagent(row: Mapping[str, object]) -> SubagentProjection:
    scope = row["tool_scope"]
    if not isinstance(scope, list):
        raise TypeError("subagent tool_scope must be a JSON array")
    return SubagentProjection(
        run_id=_uuid(row["run_id"]),
        subagent_id=_uuid(row["subagent_id"]),
        parent_subagent_id=_optional_uuid(row["parent_subagent_id"]),
        child_run_id=_optional_uuid(row["child_run_id"]),
        label=str(row["label"]),
        goal=str(row["goal"]),
        status=str(row["status"]),
        tool_scope=tuple(str(item) for item in scope),
        last_sequence=int(cast(int, row["last_sequence"])),
        started_at=_optional_datetime(row["started_at"]),
        completed_at=_optional_datetime(row["completed_at"]),
        created_at=_datetime(row["created_at"]),
        updated_at=_datetime(row["updated_at"]),
    )


class PostgresEventStore:
    """Atomic event journal, projection, history, and outbox repository."""

    def __init__(self, pool: AsyncConnectionPool[AsyncConnection[Row]]) -> None:
        self._pool = pool

    @classmethod
    def from_url(
        cls,
        database_url: str,
        *,
        min_size: int = 1,
        max_size: int = 10,
        open_pool: bool = False,
    ) -> "PostgresEventStore":
        conninfo = database_url.replace("postgresql+psycopg://", "postgresql://", 1)
        pool: AsyncConnectionPool[AsyncConnection[Row]] = AsyncConnectionPool(
            conninfo,
            min_size=min_size,
            max_size=max_size,
            open=open_pool,
            kwargs={"row_factory": dict_row},
        )
        return cls(pool)

    async def open(self) -> None:
        await self._pool.open()
        await self._pool.wait()

    async def close(self) -> None:
        await self._pool.close()

    async def migrate(self) -> tuple[str, ...]:
        async with self._pool.connection() as connection:
            return await apply_migrations(connection)

    async def create_run(self, run: NewRun) -> StoredEvent:
        if not run.title.strip():
            raise ValueError("run title must not be blank")
        async with self._pool.connection() as connection, connection.transaction():
            cursor = await connection.execute(
                """
                    INSERT INTO sentinel.runs (
                        run_id, parent_run_id, procurement_case_id,
                        request_revision_id, policy_revision, title, status, summary
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING created_at, updated_at
                    """,
                (
                    run.run_id,
                    run.parent_run_id,
                    run.procurement_case_id,
                    run.request_revision_id,
                    run.policy_revision,
                    run.title,
                    run.status,
                    run.summary,
                ),
            )
            created = await cursor.fetchone()
            if created is None:
                raise RuntimeError("PostgreSQL did not return the created run")
            await connection.execute(
                """
                    INSERT INTO sentinel.run_projection (
                        run_id, parent_run_id, title, status, summary,
                        request_revision_id, policy_revision, created_at, updated_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                (
                    run.run_id,
                    run.parent_run_id,
                    run.title,
                    run.status,
                    run.summary,
                    run.request_revision_id,
                    run.policy_revision,
                    created["created_at"],
                    created["updated_at"],
                ),
            )
            draft = EventDraft(
                event_type="run.created",
                status=run.status,
                summary=f"Created run: {run.title}",
                payload={
                    "title": run.title,
                    "status": run.status,
                    "summary": run.summary,
                    "request_revision_id": (
                        str(run.request_revision_id) if run.request_revision_id else None
                    ),
                    "policy_revision": run.policy_revision,
                },
                idempotency_key="run.created",
            )
            return await self._append_locked(connection, run.run_id, draft)

    async def append_event(self, run_id: UUID, draft: EventDraft) -> StoredEvent:
        async with self._pool.connection() as connection, connection.transaction():
            return await self._append_locked(connection, run_id, draft)

    async def _append_locked(
        self,
        connection: AsyncConnection[Row],
        run_id: UUID,
        draft: EventDraft,
    ) -> StoredEvent:
        cursor = await connection.execute(
            """
            SELECT run_id, parent_run_id, next_event_sequence
            FROM sentinel.runs
            WHERE run_id = %s
            FOR UPDATE
            """,
            (run_id,),
        )
        run_row = await cursor.fetchone()
        if run_row is None:
            raise RunNotFoundError(str(run_id))

        if draft.idempotency_key is not None:
            cursor = await connection.execute(
                """
                SELECT *
                FROM sentinel.run_events
                WHERE run_id = %s AND idempotency_key = %s
                """,
                (run_id, draft.idempotency_key),
            )
            existing = await cursor.fetchone()
            if existing is not None:
                return _stored_event(existing)

        sequence = int(cast(int, run_row["next_event_sequence"]))
        await connection.execute(
            """
            UPDATE sentinel.runs
            SET next_event_sequence = next_event_sequence + 1,
                updated_at = clock_timestamp()
            WHERE run_id = %s
            """,
            (run_id,),
        )
        cursor = await connection.execute(
            """
            INSERT INTO sentinel.run_events (
                event_id, run_id, per_run_sequence, parent_run_id, work_item_id,
                actor_id, event_type, status, causation_id, correlation_id,
                idempotency_key, summary, payload, payload_ref
            )
            VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            RETURNING *
            """,
            (
                draft.event_id,
                run_id,
                sequence,
                run_row["parent_run_id"],
                draft.work_item_id,
                draft.actor_id,
                draft.event_type,
                draft.status,
                draft.causation_id,
                draft.correlation_id,
                draft.idempotency_key,
                draft.summary,
                Jsonb(dict(draft.payload)),
                draft.payload_ref,
            ),
        )
        event_row = await cursor.fetchone()
        if event_row is None:
            raise RuntimeError("PostgreSQL did not return the appended event")
        event = _stored_event(event_row)
        await connection.execute(
            """
            INSERT INTO sentinel.event_outbox (
                event_id, run_id, per_run_sequence, topic, payload
            )
            VALUES (%s, %s, %s, %s, %s)
            """,
            (
                event.event_id,
                event.run_id,
                event.sequence,
                f"run.event.{event.event_type}",
                Jsonb(self._outbox_payload(event)),
            ),
        )
        await self._apply_projection(connection, event)
        return event

    @staticmethod
    def _outbox_payload(event: StoredEvent) -> dict[str, object]:
        return {
            "event_id": str(event.event_id),
            "run_id": str(event.run_id),
            "sequence": event.sequence,
            "parent_run_id": str(event.parent_run_id) if event.parent_run_id else None,
            "work_item_id": str(event.work_item_id) if event.work_item_id else None,
            "actor_id": event.actor_id,
            "event_type": event.event_type,
            "status": event.status,
            "causation_id": str(event.causation_id) if event.causation_id else None,
            "correlation_id": str(event.correlation_id) if event.correlation_id else None,
            "summary": event.summary,
            "payload": dict(event.payload),
            "payload_ref": event.payload_ref,
            "created_at": event.created_at.isoformat(),
        }

    async def _apply_projection(
        self,
        connection: AsyncConnection[Row],
        event: StoredEvent,
    ) -> None:
        if event.event_type.startswith("run."):
            await self._apply_run_event(connection, event)
        if event.event_type.startswith("work."):
            await self._apply_work_event(connection, event)
        if event.event_type.startswith("subagent."):
            await self._apply_subagent_event(connection, event)
        await self._refresh_run_counts(connection, event)

    async def _apply_run_event(
        self,
        connection: AsyncConnection[Row],
        event: StoredEvent,
    ) -> None:
        payload = event.payload
        updates: dict[str, object] = {}
        for key in (
            "title",
            "status",
            "summary",
            "active_phase",
            "request_revision_id",
            "policy_revision",
            "started_at",
            "completed_at",
        ):
            if key in payload:
                updates[key] = payload[key]
        if event.event_type == "run.status_changed" and "status" not in updates:
            updates["status"] = event.status
        if not updates:
            return

        status_value = updates.get("status")
        await connection.execute(
            """
            UPDATE sentinel.runs
            SET title = CASE WHEN %(has_title)s THEN %(title)s ELSE title END,
                status = CASE WHEN %(has_status)s THEN %(status)s ELSE status END,
                summary = CASE WHEN %(has_summary)s THEN %(summary)s ELSE summary END,
                request_revision_id = CASE
                    WHEN %(has_request_revision_id)s
                    THEN %(request_revision_id)s::uuid
                    ELSE request_revision_id
                END,
                policy_revision = CASE
                    WHEN %(has_policy_revision)s
                    THEN %(policy_revision)s
                    ELSE policy_revision
                END,
                started_at = CASE
                    WHEN %(has_started_at)s THEN %(started_at)s::timestamptz ELSE started_at
                END,
                completed_at = CASE
                    WHEN %(has_completed_at)s
                    THEN %(completed_at)s::timestamptz
                    ELSE completed_at
                END,
                updated_at = %(updated_at)s
            WHERE run_id = %(run_id)s
            """,
            {
                "has_title": "title" in updates,
                "title": updates.get("title"),
                "has_status": "status" in updates,
                "status": status_value,
                "has_summary": "summary" in updates,
                "summary": updates.get("summary"),
                "has_request_revision_id": "request_revision_id" in updates,
                "request_revision_id": updates.get("request_revision_id"),
                "has_policy_revision": "policy_revision" in updates,
                "policy_revision": updates.get("policy_revision"),
                "has_started_at": "started_at" in updates,
                "started_at": updates.get("started_at"),
                "has_completed_at": "completed_at" in updates,
                "completed_at": updates.get("completed_at"),
                "updated_at": event.created_at,
                "run_id": event.run_id,
            },
        )
        await connection.execute(
            """
            UPDATE sentinel.run_projection
            SET title = CASE WHEN %(has_title)s THEN %(title)s ELSE title END,
                status = CASE WHEN %(has_status)s THEN %(status)s ELSE status END,
                summary = CASE WHEN %(has_summary)s THEN %(summary)s ELSE summary END,
                active_phase = CASE
                    WHEN %(has_active_phase)s THEN %(active_phase)s ELSE active_phase
                END,
                request_revision_id = CASE
                    WHEN %(has_request_revision_id)s
                    THEN %(request_revision_id)s::uuid
                    ELSE request_revision_id
                END,
                policy_revision = CASE
                    WHEN %(has_policy_revision)s
                    THEN %(policy_revision)s
                    ELSE policy_revision
                END,
                started_at = CASE
                    WHEN %(has_started_at)s THEN %(started_at)s::timestamptz ELSE started_at
                END,
                completed_at = CASE
                    WHEN %(has_completed_at)s
                    THEN %(completed_at)s::timestamptz
                    ELSE completed_at
                END,
                updated_at = %(updated_at)s
            WHERE run_id = %(run_id)s
            """,
            {
                **{
                    "has_title": "title" in updates,
                    "title": updates.get("title"),
                    "has_status": "status" in updates,
                    "status": status_value,
                    "has_summary": "summary" in updates,
                    "summary": updates.get("summary"),
                    "has_request_revision_id": "request_revision_id" in updates,
                    "request_revision_id": updates.get("request_revision_id"),
                    "has_policy_revision": "policy_revision" in updates,
                    "policy_revision": updates.get("policy_revision"),
                    "has_started_at": "started_at" in updates,
                    "started_at": updates.get("started_at"),
                    "has_completed_at": "completed_at" in updates,
                    "completed_at": updates.get("completed_at"),
                    "updated_at": event.created_at,
                    "run_id": event.run_id,
                },
                "has_active_phase": "active_phase" in updates,
                "active_phase": updates.get("active_phase"),
            },
        )

    async def _apply_work_event(
        self,
        connection: AsyncConnection[Row],
        event: StoredEvent,
    ) -> None:
        if event.work_item_id is None:
            raise InvalidProjectionEventError("work events require work_item_id")
        cursor = await connection.execute(
            """
            SELECT *
            FROM sentinel.work_item_projection
            WHERE run_id = %s AND work_item_id = %s
            """,
            (event.run_id, event.work_item_id),
        )
        previous = await cursor.fetchone()
        payload = event.payload
        if previous is None:
            missing = [
                key
                for key in ("phase", "kind", "label")
                if not isinstance(payload.get(key), str) or not str(payload[key]).strip()
            ]
            if missing:
                joined = ", ".join(missing)
                raise InvalidProjectionEventError(
                    f"first work event requires non-blank fields: {joined}"
                )

        def value(key: str, default: object = None) -> object:
            if key in payload:
                return payload[key]
            if previous is not None:
                return previous[key]
            return default

        status_value = payload.get("status", event.status)
        await connection.execute(
            """
            INSERT INTO sentinel.work_item_projection (
                run_id, work_item_id, parent_work_item_id, subagent_id,
                phase, kind, label, status, position, completed_units,
                total_units, blocker, last_sequence, created_at, updated_at
            )
            VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            ON CONFLICT (run_id, work_item_id) DO UPDATE
            SET parent_work_item_id = EXCLUDED.parent_work_item_id,
                subagent_id = EXCLUDED.subagent_id,
                phase = EXCLUDED.phase,
                kind = EXCLUDED.kind,
                label = EXCLUDED.label,
                status = EXCLUDED.status,
                position = EXCLUDED.position,
                completed_units = EXCLUDED.completed_units,
                total_units = EXCLUDED.total_units,
                blocker = EXCLUDED.blocker,
                last_sequence = EXCLUDED.last_sequence,
                updated_at = EXCLUDED.updated_at
            WHERE sentinel.work_item_projection.last_sequence < EXCLUDED.last_sequence
            """,
            (
                event.run_id,
                event.work_item_id,
                value("parent_work_item_id"),
                value("subagent_id"),
                value("phase"),
                value("kind"),
                value("label"),
                status_value,
                value("position", 0),
                value("completed_units"),
                value("total_units"),
                value("blocker"),
                event.sequence,
                previous["created_at"] if previous is not None else event.created_at,
                event.created_at,
            ),
        )

    async def _apply_subagent_event(
        self,
        connection: AsyncConnection[Row],
        event: StoredEvent,
    ) -> None:
        raw_subagent_id = event.payload.get("subagent_id")
        if raw_subagent_id is None:
            raise InvalidProjectionEventError("subagent events require payload.subagent_id")
        subagent_id = _uuid(raw_subagent_id)
        cursor = await connection.execute(
            """
            SELECT *
            FROM sentinel.subagent_projection
            WHERE run_id = %s AND subagent_id = %s
            """,
            (event.run_id, subagent_id),
        )
        previous = await cursor.fetchone()
        payload = event.payload
        if previous is None:
            missing = [
                key
                for key in ("label", "goal")
                if not isinstance(payload.get(key), str) or not str(payload[key]).strip()
            ]
            if missing:
                joined = ", ".join(missing)
                raise InvalidProjectionEventError(
                    f"first subagent event requires non-blank fields: {joined}"
                )

        def value(key: str, default: object = None) -> object:
            if key in payload:
                return payload[key]
            if previous is not None:
                return previous[key]
            return default

        await connection.execute(
            """
            INSERT INTO sentinel.subagent_projection (
                run_id, subagent_id, parent_subagent_id, child_run_id,
                label, goal, status, tool_scope, last_sequence,
                started_at, completed_at, created_at, updated_at
            )
            VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            ON CONFLICT (run_id, subagent_id) DO UPDATE
            SET parent_subagent_id = EXCLUDED.parent_subagent_id,
                child_run_id = EXCLUDED.child_run_id,
                label = EXCLUDED.label,
                goal = EXCLUDED.goal,
                status = EXCLUDED.status,
                tool_scope = EXCLUDED.tool_scope,
                last_sequence = EXCLUDED.last_sequence,
                started_at = EXCLUDED.started_at,
                completed_at = EXCLUDED.completed_at,
                updated_at = EXCLUDED.updated_at
            WHERE sentinel.subagent_projection.last_sequence < EXCLUDED.last_sequence
            """,
            (
                event.run_id,
                subagent_id,
                value("parent_subagent_id"),
                value("child_run_id"),
                value("label"),
                value("goal"),
                payload.get("status", event.status),
                Jsonb(value("tool_scope", [])),
                event.sequence,
                value("started_at"),
                value("completed_at"),
                previous["created_at"] if previous is not None else event.created_at,
                event.created_at,
            ),
        )

    async def _refresh_run_counts(
        self,
        connection: AsyncConnection[Row],
        event: StoredEvent,
    ) -> None:
        await connection.execute(
            """
            UPDATE sentinel.run_projection AS projection
            SET completed_work_items = (
                    SELECT count(*) FROM sentinel.work_item_projection
                    WHERE run_id = %(run_id)s AND status = 'completed'
                ),
                total_work_items = (
                    SELECT count(*) FROM sentinel.work_item_projection
                    WHERE run_id = %(run_id)s
                ),
                active_subagents = (
                    SELECT count(*) FROM sentinel.subagent_projection
                    WHERE run_id = %(run_id)s
                      AND status IN ('queued', 'running', 'recovering')
                ),
                blocker_count = (
                    SELECT count(*) FROM sentinel.work_item_projection
                    WHERE run_id = %(run_id)s
                      AND (status = 'blocked' OR blocker IS NOT NULL)
                ),
                event_count = %(sequence)s,
                last_sequence = %(sequence)s,
                updated_at = %(updated_at)s
            WHERE projection.run_id = %(run_id)s
            """,
            {
                "run_id": event.run_id,
                "sequence": event.sequence,
                "updated_at": event.created_at,
            },
        )

    async def get_run(self, run_id: UUID) -> RunSummary | None:
        async with self._pool.connection() as connection:
            cursor = await connection.execute(
                "SELECT * FROM sentinel.run_projection WHERE run_id = %s",
                (run_id,),
            )
            row = await cursor.fetchone()
            return None if row is None else _run_summary(row)

    async def list_sessions(
        self,
        *,
        limit: int = 50,
        before: datetime | None = None,
    ) -> Sequence[RunSummary]:
        if not 1 <= limit <= 200:
            raise ValueError("limit must be between 1 and 200")
        async with self._pool.connection() as connection:
            cursor = await connection.execute(
                """
                SELECT *
                FROM sentinel.run_projection
                WHERE (%s::timestamptz IS NULL OR updated_at < %s)
                ORDER BY updated_at DESC, run_id DESC
                LIMIT %s
                """,
                (before, before, limit),
            )
            return tuple(_run_summary(row) for row in await cursor.fetchall())

    async def list_events(
        self,
        run_id: UUID,
        *,
        after_sequence: int = 0,
        limit: int = 500,
    ) -> Sequence[StoredEvent]:
        if after_sequence < 0:
            raise ValueError("after_sequence must not be negative")
        if not 1 <= limit <= 2_000:
            raise ValueError("limit must be between 1 and 2000")
        async with self._pool.connection() as connection:
            cursor = await connection.execute(
                """
                SELECT *
                FROM sentinel.run_events
                WHERE run_id = %s AND per_run_sequence > %s
                ORDER BY per_run_sequence
                LIMIT %s
                """,
                (run_id, after_sequence, limit),
            )
            return tuple(_stored_event(row) for row in await cursor.fetchall())

    async def list_work_items(self, run_id: UUID) -> Sequence[WorkItemProjection]:
        async with self._pool.connection() as connection:
            cursor = await connection.execute(
                """
                SELECT *
                FROM sentinel.work_item_projection
                WHERE run_id = %s
                ORDER BY phase, position, work_item_id
                """,
                (run_id,),
            )
            return tuple(_work_item(row) for row in await cursor.fetchall())

    async def list_subagents(self, run_id: UUID) -> Sequence[SubagentProjection]:
        async with self._pool.connection() as connection:
            cursor = await connection.execute(
                """
                SELECT *
                FROM sentinel.subagent_projection
                WHERE run_id = %s
                ORDER BY created_at, subagent_id
                """,
                (run_id,),
            )
            return tuple(_subagent(row) for row in await cursor.fetchall())

    async def rebuild_projections(self, run_id: UUID) -> RunSummary:
        async with self._pool.connection() as connection, connection.transaction():
            cursor = await connection.execute(
                "SELECT * FROM sentinel.runs WHERE run_id = %s FOR UPDATE",
                (run_id,),
            )
            run = await cursor.fetchone()
            if run is None:
                raise RunNotFoundError(str(run_id))
            await connection.execute(
                "DELETE FROM sentinel.work_item_projection WHERE run_id = %s",
                (run_id,),
            )
            await connection.execute(
                "DELETE FROM sentinel.subagent_projection WHERE run_id = %s",
                (run_id,),
            )
            await connection.execute(
                "DELETE FROM sentinel.run_projection WHERE run_id = %s",
                (run_id,),
            )
            await connection.execute(
                """
                    INSERT INTO sentinel.run_projection (
                        run_id, parent_run_id, title, status, summary,
                        request_revision_id, policy_revision, started_at, completed_at,
                        created_at, updated_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                (
                    run_id,
                    run["parent_run_id"],
                    run["title"],
                    run["status"],
                    run["summary"],
                    run["request_revision_id"],
                    run["policy_revision"],
                    run["started_at"],
                    run["completed_at"],
                    run["created_at"],
                    run["created_at"],
                ),
            )
            cursor = await connection.execute(
                """
                    SELECT * FROM sentinel.run_events
                    WHERE run_id = %s
                    ORDER BY per_run_sequence
                    """,
                (run_id,),
            )
            for row in await cursor.fetchall():
                await self._apply_projection(connection, _stored_event(row))
            cursor = await connection.execute(
                "SELECT * FROM sentinel.run_projection WHERE run_id = %s",
                (run_id,),
            )
            projection = await cursor.fetchone()
            if projection is None:
                raise RuntimeError("projection rebuild did not produce a run summary")
            return _run_summary(projection)

    async def claim_outbox(
        self,
        *,
        consumer_id: str,
        limit: int = 100,
        lease_seconds: int = 30,
    ) -> Sequence[OutboxMessage]:
        if not consumer_id.strip():
            raise ValueError("consumer_id must not be blank")
        if not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500")
        if not 1 <= lease_seconds <= 3_600:
            raise ValueError("lease_seconds must be between 1 and 3600")
        async with self._pool.connection() as connection, connection.transaction():
            cursor = await connection.execute(
                """
                    WITH claimable AS (
                        SELECT outbox_id
                        FROM sentinel.event_outbox
                        WHERE published_at IS NULL
                          AND available_at <= clock_timestamp()
                          AND (
                              claimed_until IS NULL
                              OR claimed_until < clock_timestamp()
                          )
                        ORDER BY outbox_id
                        FOR UPDATE SKIP LOCKED
                        LIMIT %(limit)s
                    )
                    UPDATE sentinel.event_outbox AS outbox
                    SET claimed_by = %(consumer_id)s,
                        claimed_until = clock_timestamp()
                            + %(lease_seconds)s * interval '1 second',
                        attempts = attempts + 1
                    FROM claimable
                    WHERE outbox.outbox_id = claimable.outbox_id
                    RETURNING outbox.*
                    """,
                {
                    "consumer_id": consumer_id,
                    "limit": limit,
                    "lease_seconds": lease_seconds,
                },
            )
            rows = await cursor.fetchall()
            return tuple(
                OutboxMessage(
                    outbox_id=int(cast(int, row["outbox_id"])),
                    event_id=_uuid(row["event_id"]),
                    run_id=_uuid(row["run_id"]),
                    sequence=int(cast(int, row["per_run_sequence"])),
                    topic=str(row["topic"]),
                    payload=_json_object(row["payload"]),
                    attempts=int(cast(int, row["attempts"])),
                    created_at=_datetime(row["created_at"]),
                )
                for row in rows
            )

    async def mark_outbox_published(self, *, outbox_id: int, consumer_id: str) -> bool:
        async with self._pool.connection() as connection:
            cursor = await connection.execute(
                """
                UPDATE sentinel.event_outbox
                SET published_at = clock_timestamp(),
                    claimed_by = NULL,
                    claimed_until = NULL,
                    last_error = NULL
                WHERE outbox_id = %s
                  AND claimed_by = %s
                  AND published_at IS NULL
                RETURNING outbox_id
                """,
                (outbox_id, consumer_id),
            )
            return await cursor.fetchone() is not None

    async def release_outbox(
        self,
        *,
        outbox_id: int,
        consumer_id: str,
        error: str,
    ) -> bool:
        if not error.strip():
            raise ValueError("error must not be blank")
        async with self._pool.connection() as connection:
            cursor = await connection.execute(
                """
                UPDATE sentinel.event_outbox
                SET claimed_by = NULL,
                    claimed_until = NULL,
                    available_at = clock_timestamp()
                        + least(attempts, 60) * interval '1 second',
                    last_error = %s
                WHERE outbox_id = %s
                  AND claimed_by = %s
                  AND published_at IS NULL
                RETURNING outbox_id
                """,
                (error, outbox_id, consumer_id),
            )
            return await cursor.fetchone() is not None
