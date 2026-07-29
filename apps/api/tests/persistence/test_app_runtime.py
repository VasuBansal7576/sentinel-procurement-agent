"""FastAPI-to-PostgreSQL integration proof for the walking skeleton."""

import os

import psycopg
import pytest
from fastapi.testclient import TestClient

from sentinel_api import create_app
from sentinel_api.config import get_settings


def test_postgres_lifespan_persists_walking_skeleton_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = os.getenv("SENTINEL_TEST_DATABASE_URL")
    if database_url is None:
        pytest.skip("set SENTINEL_TEST_DATABASE_URL to run PostgreSQL integration tests")
    conninfo = database_url.replace("postgresql+psycopg://", "postgresql://", 1)
    with psycopg.connect(conninfo) as connection:
        connection.execute("DROP SCHEMA IF EXISTS sentinel CASCADE")

    monkeypatch.setenv("SENTINEL_PERSISTENCE_MODE", "postgres")
    monkeypatch.setenv("SENTINEL_AUTO_MIGRATE", "true")
    monkeypatch.setenv("SENTINEL_DATABASE_URL", database_url)
    get_settings.cache_clear()
    try:
        with TestClient(create_app()) as client:
            response = client.post(
                "/api/runs",
                json={
                    "title": "Durable printer refresh",
                    "item_name": "Industrial label printer",
                    "description": "Networked thermal printer",
                    "quantity": "4",
                    "unit": "each",
                },
            )
        assert response.status_code == 201
        run_id = response.json()["id"]
        with psycopg.connect(conninfo) as connection:
            event_count = connection.execute(
                "SELECT count(*) FROM sentinel.run_events WHERE run_id = %s",
                (run_id,),
            ).fetchone()
            projection = connection.execute(
                """
                SELECT status, event_count, last_sequence
                FROM sentinel.run_projection
                WHERE run_id = %s
                """,
                (run_id,),
            ).fetchone()
        assert event_count == (4,)
        assert projection == ("completed", 4, 4)
    finally:
        get_settings.cache_clear()
