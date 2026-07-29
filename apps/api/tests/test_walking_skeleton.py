from fastapi.testclient import TestClient

from sentinel_api import create_app


def test_run_crosses_api_events_and_artifact_boundaries() -> None:
    client = TestClient(create_app())

    created = client.post(
        "/api/runs",
        json={
            "title": "Replace warehouse label printers",
            "item_name": "Industrial label printer",
            "description": "Networked thermal printer with 300 dpi resolution",
            "quantity": "4",
            "unit": "each",
        },
    )

    assert created.status_code == 201
    run = created.json()
    assert run["status"] == "completed"
    assert [event["event_type"] for event in run["events"]] == [
        "run.created",
        "request.normalized",
        "artifact.created",
        "run.completed",
    ]

    replay = client.get(
        f"/api/runs/{run['id']}/events",
        headers={"Last-Event-ID": "2"},
    )
    assert replay.status_code == 200
    assert replay.headers["content-type"].startswith("text/event-stream")
    assert "id: 3" in replay.text
    assert "id: 1" not in replay.text

    artifact = run["artifacts"][0]
    download = client.get(artifact["download_url"])
    assert download.status_code == 200
    assert "attachment; filename=" in download.headers["content-disposition"]
    assert download.headers["cache-control"] == "private, no-store"
    assert download.headers["content-security-policy"] == "default-src 'none'; sandbox"
    assert len(download.headers["x-content-sha256"]) == 64
    assert "Industrial label printer" in download.text


def test_missing_run_is_explicit() -> None:
    client = TestClient(create_app())

    response = client.get("/api/runs/00000000-0000-0000-0000-000000000000")

    assert response.status_code == 404
    assert response.json() == {"detail": "Run not found"}
