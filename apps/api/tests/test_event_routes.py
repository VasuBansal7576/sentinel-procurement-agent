"""HTTP boundary tests for run event stream cursor validation."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from sentinel_api.routes.events import router


class MissingRunStore:
    async def get_run(self, _run_id: object) -> None:
        return None


def test_event_stream_requires_configured_store() -> None:
    app = FastAPI()
    app.include_router(router, prefix="/api")

    with TestClient(app) as client:
        response = client.get("/api/runs/30b57884-02da-44ba-8360-ff42e5d1f485/events")

    assert response.status_code == 503
    assert response.json() == {"detail": "event store is not configured"}


def test_event_stream_rejects_invalid_last_event_id_before_store_access() -> None:
    app = FastAPI()
    app.include_router(router, prefix="/api")

    with TestClient(app) as client:
        response = client.get(
            "/api/runs/30b57884-02da-44ba-8360-ff42e5d1f485/events",
            headers={"Last-Event-ID": "not-a-sequence"},
        )

    assert response.status_code == 400
    assert response.json() == {"detail": "Last-Event-ID must be a non-negative integer"}


def test_event_stream_returns_not_found_before_starting_stream() -> None:
    app = FastAPI()
    app.state.event_store = MissingRunStore()
    app.include_router(router, prefix="/api")

    with TestClient(app) as client:
        response = client.get("/api/runs/30b57884-02da-44ba-8360-ff42e5d1f485/events")

    assert response.status_code == 404
    assert response.json() == {"detail": "run not found"}
