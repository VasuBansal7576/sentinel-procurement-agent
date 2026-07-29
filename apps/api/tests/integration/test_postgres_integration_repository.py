"""Real PostgreSQL proof for compact records and run-scoped artifact bytes."""

import os
from uuid import uuid4

import pytest
from psycopg import AsyncConnection

from sentinel_api.integration.models import IntegrationRecord
from sentinel_api.integration.repository import PostgresIntegrationRepository
from sentinel_api.persistence import NewRun, PostgresEventStore

pytestmark = pytest.mark.asyncio


def _database_url() -> str:
    value = os.getenv("SENTINEL_TEST_DATABASE_URL")
    if value is None:
        pytest.skip("set SENTINEL_TEST_DATABASE_URL to run PostgreSQL integration tests")
    return value


async def test_records_are_idempotent_and_artifacts_are_run_scoped() -> None:
    database_url = _database_url()
    connection = await AsyncConnection.connect(
        database_url.replace("postgresql+psycopg://", "postgresql://", 1)
    )
    await connection.execute("DROP SCHEMA IF EXISTS sentinel CASCADE")
    await connection.commit()
    await connection.close()
    event_store = PostgresEventStore.from_url(database_url)
    await event_store.open()
    try:
        assert await event_store.migrate() == (
            "0001",
            "0002",
            "0003",
            "0004",
            "0005",
        )
        first_run = NewRun(title="First integration run")
        second_run = NewRun(title="Second integration run")
        await event_store.create_run(first_run)
        await event_store.create_run(second_run)
        repository = PostgresIntegrationRepository(event_store.connection_pool)
        artifact = IntegrationRecord(
            run_id=first_run.run_id,
            record_ref=uuid4(),
            record_kind="artifact",
            payload={"kind": "recommendation_report"},
            content=b"opaque report bytes",
            filename="recommendation.md",
            media_type="text/markdown",
            content_sha256=("1f33eafe4b790f61bc5d978d309bef7a914c46ef0a3de272be0e694f559fd75c"),
        )

        stored = await repository.put(artifact)
        duplicate = await repository.put(artifact)

        assert duplicate == stored
        assert await repository.get(first_run.run_id, artifact.record_ref) == stored
        assert await repository.get(second_run.run_id, artifact.record_ref) is None
        assert await repository.list(first_run.run_id, record_kind="artifact") == (stored,)
        with pytest.raises(ValueError, match="different content"):
            await repository.put(artifact.model_copy(update={"payload": {"kind": "changed"}}))
        assert await event_store.migrate() == ()
    finally:
        await event_store.close()
