"""Credential-free category-generic integration acceptance tests."""

import asyncio
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from sentinel_api import create_app
from sentinel_api.domain import ActionOutcomeState
from sentinel_api.integration.protected import FakeProtectedEmailBoundary
from sentinel_api.persistence.models import EventDraft
from sentinel_api.persistence.protocols import EventStore
from sentinel_api.workflows.models import RetryWorkCommand

CATEGORIES = (
    {
        "title": "Replace process transfer pumps",
        "item_name": "Industrial transfer pump",
        "description": "Corrosion-resistant continuous-duty equipment",
        "quantity": "3",
        "unit": "each",
    },
    {
        "title": "Replenish recurring PPE",
        "item_name": "Chemical-resistant gloves",
        "description": "Recurring supply of reusable safety gloves",
        "quantity": "2400",
        "unit": "pair",
    },
    {
        "title": "Renew calibration services",
        "item_name": "Accredited calibration service",
        "description": "Annual on-site calibration for production instruments",
        "quantity": "18",
        "unit": "instrument",
    },
)


class RecordingRetryRuntime:
    def __init__(self, event_store: EventStore) -> None:
        self.event_store = event_store
        self.commands: list[RetryWorkCommand] = []

    async def retry(self, run_id: UUID, command: RetryWorkCommand) -> object:
        self.commands.append(command)
        await self.event_store.append_event(
            run_id,
            EventDraft(
                event_type="work.retry_requested",
                status="recovering",
                summary=command.reason,
                payload={
                    "status": "recovering",
                    "failed_attempt": command.expected_attempt,
                    "next_attempt": command.expected_attempt + 1,
                },
                work_item_id=UUID(command.work_item_id),
                actor_id="operator",
                idempotency_key=f"command:{command.command_id}:applied",
            ),
        )
        return {"accepted": True}


@pytest.mark.parametrize("intake", CATEGORIES)
def test_unrelated_categories_share_the_real_pipeline(intake: dict[str, str]) -> None:
    with TestClient(create_app()) as client:
        response = client.post("/api/operator/runs", json=intake)

        assert response.status_code == 201, response.text
        run = response.json()
        assert run["session"]["title"] == intake["title"]
        assert run["session"]["status"] == "completed"
        assert run["session"]["revision"] == 1
        assert len(run["requirements"]) == 3
        assert len(run["candidates"]) == 3
        assert {candidate["evidenceCoverage"] for candidate in run["candidates"]} == {"33%"}
        assert len(run["evidence"]) == 9
        assert len(run["artifacts"]) == 4
        assert run["proposal"]["status"] == "pending_approval"
        assert run["workTree"][0]["children"][0]["children"][0]["children"]

        run_id = UUID(run["session"]["id"])
        events = client.get(
            f"/api/runs/{run_id}/events",
            headers={"Last-Event-ID": "0"},
        )
        assert events.status_code == 200
        assert events.text.count("event: tool.started") > 20
        assert events.text.count("event: tool.completed") > 20
        assert '"content":' not in events.text


def test_operator_commands_proposals_and_run_scoped_downloads() -> None:
    app = create_app()
    with TestClient(app) as client:
        created = client.post("/api/operator/runs", json=CATEGORIES[0]).json()
        run_id = created["session"]["id"]
        asyncio.run(
            app.state.integration_service.event_store.append_event(
                UUID(run_id),
                EventDraft(
                    event_type="run.status_changed",
                    status="running",
                    summary="Opened command acceptance window",
                    payload={"status": "running", "active_phase": "integration"},
                    idempotency_key="test.command-window",
                ),
            )
        )

        sessions = client.get("/api/operator/sessions")
        assert sessions.status_code == 200
        assert sessions.json()[0]["id"] == run_id
        tree = client.get(f"/api/operator/runs/{run_id}/work-tree")
        assert tree.status_code == 200
        assert tree.json()[0]["label"] == "Integration"

        paused = client.post(
            f"/api/operator/runs/{run_id}/controls/pause",
            json={"command_id": str(uuid4()), "reason": "Inspect evidence"},
        )
        assert paused.status_code == 200
        assert paused.json()["session"]["status"] == "paused"
        resumed = client.post(
            f"/api/operator/runs/{run_id}/controls/resume",
            json={"command_id": str(uuid4()), "reason": "Continue run"},
        )
        assert resumed.status_code == 200
        assert resumed.json()["session"]["status"] == "running"

        queued = client.post(
            f"/api/operator/runs/{run_id}/messages",
            json={
                "command_id": str(uuid4()),
                "message_id": str(uuid4()),
                "text": "Preserve verified supplier evidence.",
            },
        )
        assert queued.status_code == 200
        assert queued.json()["commands"][0]["text"] == ("Preserve verified supplier evidence.")
        redirected = client.post(
            f"/api/operator/runs/{run_id}/redirect",
            json={
                "command_id": (redirect_command_id := str(uuid4())),
                "text": "Require mobilization within twenty days.",
                "changed_dependencies": ["request:requirements"],
            },
        )
        assert redirected.status_code == 200
        assert redirected.json()["session"]["revision"] == 2
        duplicate_redirect = client.post(
            f"/api/operator/runs/{run_id}/redirect",
            json={
                "command_id": redirect_command_id,
                "text": "Require mobilization within twenty days.",
                "changed_dependencies": ["request:requirements"],
            },
        )
        assert duplicate_redirect.status_code == 200
        assert duplicate_redirect.json()["session"]["revision"] == 2

        proposal = redirected.json()["proposal"]
        edited = client.put(
            f"/api/operator/runs/{run_id}/proposal",
            json={
                "recipient": "procurement-demo@example.test",
                "subject": "Updated controlled RFQ",
                "body": "Please quote the exact revised requirement.",
            },
        )
        assert edited.status_code == 200, edited.text
        assert edited.json()["proposal"]["current"]["version"] == (
            proposal["current"]["version"] + 1
        )
        approved = client.post(
            f"/api/operator/runs/{run_id}/proposal/decision",
            json={"decision": "approve", "approver_id": str(uuid4())},
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()["proposal"]["status"] == "approved"
        assert (
            approved.json()["proposal"]["current"]["digest"]
            == (edited.json()["proposal"]["current"]["digest"])
        )

        artifact = created["artifacts"][0]
        download = client.get(artifact["downloadUrl"])
        assert download.status_code == 200
        assert download.headers["cache-control"] == "private, no-store"
        assert download.headers["content-security-policy"] == "default-src 'none'; sandbox"
        assert download.headers["x-content-type-options"] == "nosniff"
        assert download.headers["x-content-sha256"] == artifact["digest"].removeprefix("sha256:")
        wrong_run = client.get(f"/api/runs/{uuid4()}/artifacts/{artifact['id']}")
        assert wrong_run.status_code == 404

        work_id = created["workTree"][0]["children"][0]["children"][0]["id"]
        retry = client.post(
            f"/api/operator/runs/{run_id}/work/{work_id}/retry",
            json={"command_id": str(uuid4())},
        )
        assert retry.status_code == 409
        assert "safe-to-retry" in retry.json()["detail"]


def test_rejection_is_version_bound_and_never_dispatches() -> None:
    app = create_app()
    with TestClient(app) as client:
        created = client.post("/api/operator/runs", json=CATEGORIES[2]).json()
        run_id = created["session"]["id"]
        rejected = client.post(
            f"/api/operator/runs/{run_id}/proposal/decision",
            json={"decision": "reject", "approver_id": str(uuid4())},
        )

        assert rejected.status_code == 200
        assert rejected.json()["proposal"]["status"] == "rejected"
        assert app.state.email_execution_store is not None


def test_retryable_failure_binds_the_exact_failed_attempt_to_runtime() -> None:
    app = create_app()
    with TestClient(app) as client:
        created = client.post("/api/operator/runs", json=CATEGORIES[0]).json()
        run_id = UUID(created["session"]["id"])
        work_id = UUID(created["workTree"][0]["children"][0]["children"][0]["id"])
        runtime = RecordingRetryRuntime(app.state.integration_service.event_store)
        app.state.integration_service.runtime = runtime
        asyncio.run(
            app.state.integration_service.event_store.append_event(
                run_id,
                EventDraft(
                    event_type="work.failed",
                    status="failed",
                    summary="Transient tool retries exhausted",
                    payload={
                        "status": "failed",
                        "attempt": 3,
                        "blocker": "transient",
                        "completed_units": 0,
                        "total_units": 1,
                    },
                    work_item_id=work_id,
                    idempotency_key="test.retryable-failure",
                ),
            )
        )

        retry = client.post(
            f"/api/operator/runs/{run_id}/work/{work_id}/retry",
            json={"command_id": str(uuid4())},
        )

        assert retry.status_code == 200
        assert len(runtime.commands) == 1
        assert runtime.commands[0].work_item_id == str(work_id)
        assert runtime.commands[0].expected_attempt == 3
        work = retry.json()["workTree"][0]["children"][0]["children"][0]
        assert work["status"] == "recovering"


def test_exact_approval_can_cross_only_the_fake_controlled_email_boundary() -> None:
    app = create_app()
    with TestClient(app) as client:
        created = client.post("/api/operator/runs", json=CATEGORIES[1]).json()
        run_id = UUID(created["session"]["id"])
        approved = client.post(
            f"/api/operator/runs/{run_id}/proposal/decision",
            json={"decision": "approve", "approver_id": str(uuid4())},
        )
        assert approved.status_code == 200
        decisions = asyncio.run(
            app.state.integration_service.records.list(
                run_id,
                record_kind="proposal_decision",
            )
        )
        decision = decisions[-1]
        boundary = FakeProtectedEmailBoundary(
            broker=app.state.approval_broker,
            store=app.state.email_execution_store,
        )

        outcome = asyncio.run(
            boundary.execute(
                run_id=run_id,
                permit_id=UUID(str(decision.payload["permit_id"])),
                proposal_id=UUID(str(decision.payload["proposal_id"])),
            )
        )

        assert outcome.state is ActionOutcomeState.CONFIRMED
        assert len(boundary.provider.dispatch_calls) == 1
        assert (
            boundary.provider.dispatch_calls[0].message.recipient == "procurement-demo@example.test"
        )
