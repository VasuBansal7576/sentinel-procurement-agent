"""Composable application lifespan for the PostgreSQL event store."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sentinel_api.persistence.postgres import PostgresEventStore


@asynccontextmanager
async def event_store_runtime(
    database_url: str,
    *,
    migrate: bool = False,
) -> AsyncIterator[PostgresEventStore]:
    """Open a pool for an application lifespan and close it reliably.

    Production deployments should normally run migrations as a release step.
    ``migrate=True`` is useful for local development and isolated tests.
    """

    store = PostgresEventStore.from_url(database_url)
    await store.open()
    try:
        if migrate:
            await store.migrate()
        yield store
    finally:
        await store.close()
