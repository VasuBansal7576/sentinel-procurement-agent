"""Compact integration-record repositories."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Protocol, cast
from uuid import UUID

from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from sentinel_api.integration.models import IntegrationRecord

Row = dict[str, object]


class IntegrationRepository(Protocol):
    async def put(self, record: IntegrationRecord) -> IntegrationRecord: ...

    async def get(self, run_id: UUID, record_ref: UUID) -> IntegrationRecord | None: ...

    async def list(
        self,
        run_id: UUID,
        *,
        record_kind: str | None = None,
    ) -> Sequence[IntegrationRecord]: ...


class InMemoryIntegrationRepository:
    """Idempotent run-scoped record storage used by tests and demo fallback."""

    def __init__(self) -> None:
        self._records: dict[tuple[UUID, UUID], IntegrationRecord] = {}

    async def put(self, record: IntegrationRecord) -> IntegrationRecord:
        key = (record.run_id, record.record_ref)
        existing = self._records.get(key)
        if existing is not None:
            comparable_existing = existing.model_copy(
                update={"created_at": record.created_at, "updated_at": record.updated_at}
            )
            if comparable_existing != record:
                raise ValueError("integration record reference was reused with different content")
            return existing
        self._records[key] = record
        return record

    async def get(self, run_id: UUID, record_ref: UUID) -> IntegrationRecord | None:
        return self._records.get((run_id, record_ref))

    async def list(
        self,
        run_id: UUID,
        *,
        record_kind: str | None = None,
    ) -> Sequence[IntegrationRecord]:
        records = (
            record
            for (owner_id, _), record in self._records.items()
            if owner_id == run_id and (record_kind is None or record.record_kind == record_kind)
        )
        return tuple(
            sorted(
                records,
                key=lambda record: (record.created_at, str(record.record_ref)),
            )
        )


def _datetime(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"expected datetime, got {type(value).__name__}")
    return value


def _record(row: Mapping[str, object]) -> IntegrationRecord:
    payload = row["payload"]
    if not isinstance(payload, Mapping):
        raise TypeError("integration record payload must be a JSON object")
    content = row["content"]
    if content is not None and not isinstance(content, bytes):
        content = bytes(cast(memoryview, content))
    return IntegrationRecord(
        run_id=UUID(str(row["run_id"])),
        record_ref=UUID(str(row["record_ref"])),
        record_kind=str(row["record_kind"]),
        payload=dict(payload),
        content=content,
        filename=cast(str | None, row["filename"]),
        media_type=cast(str | None, row["media_type"]),
        content_sha256=cast(str | None, row["content_sha256"]),
        version=int(cast(int, row["version"])),
        created_at=_datetime(row["created_at"]),
        updated_at=_datetime(row["updated_at"]),
    )


class PostgresIntegrationRepository:
    """PostgreSQL adapter for the additive PR 11 integration table."""

    def __init__(self, pool: AsyncConnectionPool[AsyncConnection[Row]]) -> None:
        self._pool = pool

    @classmethod
    def from_url(cls, database_url: str) -> PostgresIntegrationRepository:
        conninfo = database_url.replace("postgresql+psycopg://", "postgresql://", 1)
        pool: AsyncConnectionPool[AsyncConnection[Row]] = AsyncConnectionPool(
            conninfo,
            open=False,
            kwargs={"row_factory": dict_row},
        )
        return cls(pool)

    async def put(self, record: IntegrationRecord) -> IntegrationRecord:
        async with self._pool.connection() as connection:
            cursor = await connection.execute(
                """
                INSERT INTO sentinel.integration_records (
                    run_id, record_ref, record_kind, payload, content, filename,
                    media_type, content_sha256, version, created_at, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (run_id, record_ref) DO NOTHING
                RETURNING *
                """,
                (
                    record.run_id,
                    record.record_ref,
                    record.record_kind,
                    Jsonb(record.payload),
                    record.content,
                    record.filename,
                    record.media_type,
                    record.content_sha256,
                    record.version,
                    record.created_at,
                    record.updated_at,
                ),
            )
            row = await cursor.fetchone()
            if row is not None:
                return _record(row)
            existing = await self.get(record.run_id, record.record_ref)
            if existing is None:
                raise RuntimeError("integration record insert lost its conflict row")
            comparable_existing = existing.model_copy(
                update={"created_at": record.created_at, "updated_at": record.updated_at}
            )
            if comparable_existing != record:
                raise ValueError("integration record reference was reused with different content")
            return existing

    async def get(self, run_id: UUID, record_ref: UUID) -> IntegrationRecord | None:
        async with self._pool.connection() as connection:
            cursor = await connection.execute(
                """
                SELECT * FROM sentinel.integration_records
                WHERE run_id = %s AND record_ref = %s
                """,
                (run_id, record_ref),
            )
            row = await cursor.fetchone()
        return None if row is None else _record(row)

    async def list(
        self,
        run_id: UUID,
        *,
        record_kind: str | None = None,
    ) -> Sequence[IntegrationRecord]:
        async with self._pool.connection() as connection:
            if record_kind is None:
                cursor = await connection.execute(
                    """
                    SELECT * FROM sentinel.integration_records
                    WHERE run_id = %s
                    ORDER BY created_at, record_ref
                    """,
                    (run_id,),
                )
            else:
                cursor = await connection.execute(
                    """
                    SELECT * FROM sentinel.integration_records
                    WHERE run_id = %s AND record_kind = %s
                    ORDER BY created_at, record_ref
                    """,
                    (run_id, record_kind),
                )
            rows = await cursor.fetchall()
        return tuple(_record(row) for row in rows)
