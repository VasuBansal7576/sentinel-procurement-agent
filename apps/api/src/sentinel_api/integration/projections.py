"""Map durable backend records to the operator workbench contract."""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import cast
from uuid import UUID

from sentinel_api.domain import (
    AutonomyMode,
    ProposalVersion,
    autonomy_label,
    autonomy_policy_decision,
)
from sentinel_api.integration.brokers import ApprovalBrokerAdapter, await_result
from sentinel_api.integration.models import IntegrationRecord
from sentinel_api.persistence.models import (
    RunSummary,
    StoredEvent,
    SubagentProjection,
    WorkItemProjection,
)
from sentinel_api.persistence.protocols import EventStore

HONESTY_BANNER = (
    "Deterministic local suppliers · not live market data · "
    "approval records permission only and never sends"
)
SOURCE_BOUNDARY = (
    "Credential-free execution boundary: local synthetic research documents, "
    "fake email provider, durable Temporal/PostgreSQL control plane."
)


async def session_view(
    summary: RunSummary,
    records: Sequence[IntegrationRecord],
) -> dict[str, object]:
    request = _latest(records, "request", "request_revision")
    intake = request.payload.get("intake", {}) if request else {}
    if not isinstance(intake, dict):
        intake = {}
    revision = request.payload.get("revision", {}) if request else {}
    if not isinstance(revision, dict):
        revision = {}
    quantity = intake.get("quantity", "")
    unit = intake.get("unit", "")
    return {
        "id": str(summary.run_id),
        "title": summary.title,
        "requestLabel": f"{quantity} {unit}".strip() or "Procurement request",
        "status": _run_status(summary.status),
        "updatedLabel": _relative(summary.updated_at),
        "revision": int(revision.get("revision_number", 1)),
    }


async def operator_run_view(
    *,
    event_store: EventStore,
    records: Sequence[IntegrationRecord],
    summary: RunSummary,
    proposal_broker: ApprovalBrokerAdapter,
) -> dict[str, object]:
    events = await event_store.list_events(summary.run_id, limit=500)
    work = await event_store.list_work_items(summary.run_id)
    subagents = await event_store.list_subagents(summary.run_id)
    session = await session_view(summary, records)
    request = _latest(records, "request", "request_revision")
    revision_payload = request.payload.get("revision", {}) if request else {}
    requirements = _requirements(revision_payload)
    candidate_record = _latest(records, "candidates")
    evidence_record = _latest(records, "evidence")
    evaluation_record = _latest(records, "evaluation")
    candidates = _candidates(candidate_record, evaluation_record)
    evidence = _evidence(evidence_record, candidates)
    mode = resolve_autonomy(records)
    label = autonomy_label(mode)
    proposal = await _proposal(records, proposal_broker)
    if mode is AutonomyMode.RESEARCH_ONLY:
        proposal = None
    elif isinstance(proposal, dict):
        proposal = {
            **proposal,
            "policyDecision": (
                f"{autonomy_policy_decision(mode)}; fake provider only"
            ),
            "autonomyMode": mode.value,
        }
    return {
        "session": session,
        "summary": summary.summary or "Credential-free procurement integration",
        "activePhase": (summary.active_phase or "intake").replace("_", " ").title(),
        "autonomyMode": mode.value,
        "autonomyLabel": label,
        "autonomyOptions": [
            {
                "value": AutonomyMode.RESEARCH_ONLY.value,
                "label": autonomy_label(AutonomyMode.RESEARCH_ONLY),
                "description": (
                    "Compare suppliers and produce files only. "
                    "No RFQ proposal and no external contact path."
                ),
            },
            {
                "value": AutonomyMode.ASK_BEFORE_EXTERNAL.value,
                "label": autonomy_label(AutonomyMode.ASK_BEFORE_EXTERNAL),
                "description": (
                    "Research freely, then pause for exact human approval "
                    "before any external contact is authorized."
                ),
            },
            {
                "value": AutonomyMode.APPROVE_AND_HOLD.value,
                "label": autonomy_label(AutonomyMode.APPROVE_AND_HOLD),
                "description": (
                    "Exact approval is allowed, but dispatch never happens "
                    "automatically. Hold the permit until a separate gated send."
                ),
            },
        ],
        "policyLabel": f"{label} · rev {summary.policy_revision or 1}",
        "honestyBanner": HONESTY_BANNER,
        "sourceBoundary": SOURCE_BOUNDARY,
        "elapsedLabel": _elapsed(summary),
        "progress": {
            "completed": summary.completed_work_items,
            "total": summary.total_work_items,
            "active": summary.active_subagents,
            "blockers": summary.blocker_count,
        },
        "workTree": _work_tree(work, subagents, events),
        "requirements": requirements,
        "candidates": candidates,
        "evidence": evidence,
        "artifacts": _artifacts(records),
        "proposal": proposal,
        "commands": _commands(events),
    }


def resolve_autonomy(records: Sequence[IntegrationRecord]) -> AutonomyMode:
    settings = [
        record
        for record in records
        if record.record_kind == "autonomy_mode"
    ]
    if settings:
        latest = max(settings, key=lambda record: (record.version, record.updated_at))
        raw = latest.payload.get("autonomy_mode")
        if raw is not None:
            try:
                return AutonomyMode(str(raw))
            except ValueError:
                pass
    request = _latest(records, "request", "request_revision")
    if request is not None:
        raw = request.payload.get("autonomy_mode")
        intake = request.payload.get("intake")
        if raw is None and isinstance(intake, dict):
            raw = intake.get("autonomy_mode")
        if raw is not None:
            try:
                return AutonomyMode(str(raw))
            except ValueError:
                pass
    return AutonomyMode.ASK_BEFORE_EXTERNAL


def _latest(
    records: Sequence[IntegrationRecord],
    *kinds: str,
) -> IntegrationRecord | None:
    matching = [record for record in records if record.record_kind in kinds]
    return max(matching, key=lambda record: (record.version, record.created_at), default=None)


def _run_status(status: str) -> str:
    mapping = {
        "completed_with_failures": "failed",
        "pending": "queued",
    }
    return mapping.get(status, status)


def _relative(value: datetime) -> str:
    now = datetime.now(UTC)
    delta = max(0, int((now - value).total_seconds()))
    if delta < 60:
        return "just now"
    if delta < 3600:
        return f"{delta // 60}m ago"
    if delta < 86400:
        return f"{delta // 3600}h ago"
    return f"{delta // 86400}d ago"


def _elapsed(summary: RunSummary) -> str:
    if summary.started_at is None:
        return "not started"
    end = summary.completed_at or datetime.now(UTC)
    seconds = max(0, int((end - summary.started_at).total_seconds()))
    return f"{seconds}s" if seconds < 60 else f"{seconds // 60}m"


def _work_state(status: str) -> str:
    return {
        "queued": "remaining",
        "pending": "remaining",
        "running": "active",
        "completed_with_failures": "failed",
    }.get(status, status)


def _work_tree(
    work: Sequence[WorkItemProjection],
    subagents: Sequence[SubagentProjection],
    events: Sequence[StoredEvent],
) -> list[dict[str, object]]:
    phases: dict[str, list[dict[str, object]]] = {}
    for item in work:
        tool_events = [
            event
            for event in events
            if event.work_item_id == item.work_item_id and event.event_type == "tool.completed"
        ]
        children = [
            {
                "id": str(event.event_id),
                "label": str(event.payload.get("tool", event.summary)),
                "kind": "tool",
                "status": "completed",
                "summary": event.summary,
            }
            for event in tool_events
        ]
        agent = next(
            (entry for entry in subagents if entry.subagent_id == item.subagent_id),
            None,
        )
        work_node: dict[str, object] = {
            "id": str(item.work_item_id),
            "label": item.label,
            "kind": "work",
            "status": _work_state(item.status),
            "summary": (f"{len(tool_events)} credential-free tool activities recorded."),
            "children": children,
        }
        if item.blocker:
            work_node["blocker"] = item.blocker
            work_node["retry"] = {
                "attempt": 1,
                "maxAttempts": 3,
                "classification": item.blocker,
                "safeToRetry": item.blocker in {"transient", "rate_limited"},
            }
        subagent_node: dict[str, object] = {
            "id": str(agent.subagent_id) if agent else f"agent-{item.work_item_id}",
            "label": agent.label if agent else item.label,
            "kind": "subagent",
            "status": _work_state(agent.status if agent else item.status),
            "summary": agent.goal if agent else item.label,
            "children": [work_node],
        }
        phases.setdefault(item.phase, []).append(subagent_node)
    return [
        {
            "id": f"phase-{phase}",
            "label": phase.replace("_", " ").title(),
            "kind": "phase",
            "status": (
                "failed"
                if any(child["status"] == "failed" for child in children)
                else (
                    "completed"
                    if children and all(child["status"] == "completed" for child in children)
                    else "active"
                )
            ),
            "summary": f"{len(children)} bounded subagent assignment(s).",
            "children": children,
        }
        for phase, children in phases.items()
    ]


def _requirements(raw_revision: object) -> list[dict[str, object]]:
    if not isinstance(raw_revision, dict):
        return []
    result = []
    for lot in raw_revision.get("lots", []):
        for line_item in lot.get("line_items", []):
            for requirement in line_item.get("requirements", []):
                criterion = requirement.get("criterion", {})
                target = criterion.get("target")
                unit = criterion.get("unit") or criterion.get("currency") or ""
                result.append(
                    {
                        "id": requirement["key"],
                        "label": requirement["label"],
                        "value": f"{target} {unit}".strip(),
                        "mandatory": requirement["priority"] == "mandatory",
                    }
                )
    return result


def _candidates(
    candidate_record: IntegrationRecord | None,
    evaluation_record: IntegrationRecord | None,
) -> list[dict[str, object]]:
    if candidate_record is None:
        return []
    evaluations = {}
    if evaluation_record is not None:
        evaluations = {
            item["candidate_id"]: item
            for item in cast(list[dict[str, object]], evaluation_record.payload["candidates"])
        }
    result = []
    for raw in cast(list[dict[str, object]], candidate_record.payload["candidates"]):
        candidate_id = str(raw["id"])
        supplier = cast(dict[str, object], raw["supplier"])
        evaluation = cast(dict[str, object], evaluations.get(candidate_id, {}))
        requirement_results = cast(list[dict[str, object]], evaluation.get("requirements", []))
        claims = [
            {
                "requirementId": item["key"],
                "displayValue": str(item.get("value")),
                "state": _evidence_state(str(item["status"])),
                "observationIds": item["observation_ids"],
            }
            for item in requirement_results
        ]
        attributes = cast(dict[str, object], raw.get("attributes", {}))
        quoted_price = cast(dict[str, object] | None, raw.get("quoted_price"))
        result.append(
            {
                "id": candidate_id,
                "name": supplier["legal_name"],
                "location": supplier.get("country_code") or "Unknown",
                "totalCost": (
                    f"{quoted_price['currency']} {quoted_price['amount']}"
                    if quoted_price
                    else "Unknown"
                ),
                "leadTime": next(
                    (
                        str(item.get("value"))
                        for item in requirement_results
                        if item["key"] == "lead_time"
                    ),
                    "Unknown",
                ),
                "evidenceCoverage": _percentage(evaluation.get("coverage", "0")),
                "mandatoryStatus": (
                    "pass"
                    if evaluation.get("eligible") is True
                    else ("fail" if evaluation.get("failed_mandatory") else "review")
                ),
                "claims": claims,
                "_sourceUrl": raw.get("source_url"),
                "_description": attributes.get("description", ""),
            }
        )
    return result


def _percentage(value: object) -> str:
    try:
        rounded = Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        rounded = Decimal(0)
    return f"{rounded}%"


def _evidence_state(status: str) -> str:
    return {
        "satisfied": "supported",
        "not_satisfied": "supported",
        "operator_provided": "operator-provided",
        "calculated": "calculated",
    }.get(status, status if status in {"conflicting", "unknown"} else "unknown")


def _evidence(
    evidence_record: IntegrationRecord | None,
    candidates: list[dict[str, object]],
) -> list[dict[str, object]]:
    if evidence_record is None:
        return []
    candidate_by_id = {str(item["id"]): item for item in candidates}
    result = []
    for raw in cast(list[dict[str, object]], evidence_record.payload["observations"]):
        source = cast(dict[str, object], raw.get("source") or {})
        candidate = candidate_by_id.get(str(raw.get("candidate_id")), {})
        result.append(
            {
                "id": raw["id"],
                "candidateId": raw.get("candidate_id"),
                "requirementId": raw["requirement_key"],
                "title": (f"Verified {str(raw['requirement_key']).replace('_', ' ')}"),
                "value": str(raw.get("value")),
                "state": _evidence_state(str(raw["classification"])),
                "sourceLabel": candidate.get("name", "Credential-free source"),
                "sourceUrl": source.get("url", ""),
                "observedAt": str(source.get("retrieved_at", "")),
                "excerpt": source.get("exact_span", ""),
                "contentHash": f"sha256:{source.get('content_sha256', '')}",
            }
        )
    return result


def _artifacts(records: Sequence[IntegrationRecord]) -> list[dict[str, object]]:
    return [
        {
            "id": str(record.record_ref),
            "filename": record.filename,
            "kind": record.payload["kind"],
            "mediaType": record.media_type,
            "sizeLabel": f"{len(record.content or b'')} bytes",
            "version": record.version,
            "status": record.payload.get("status", "ready"),
            "downloadUrl": (f"/api/runs/{record.run_id}/artifacts/{record.record_ref}"),
            "digest": f"sha256:{record.content_sha256}",
        }
        for record in records
        if record.record_kind == "artifact"
    ]


async def _proposal(
    records: Sequence[IntegrationRecord],
    broker: ApprovalBrokerAdapter,
) -> dict[str, object] | None:
    reference = _latest(records, "proposal_ref")
    if reference is None:
        return None
    proposal_id = UUID(str(reference.payload["proposal_id"]))
    proposal = await await_result(broker.get_proposal(proposal_id))
    current_version = int(proposal.current_version)
    current = await await_result(broker.get_version(proposal_id, current_version))
    previous = (
        await await_result(broker.get_version(proposal_id, current_version - 1))
        if current_version > 1
        else None
    )
    decisions = [
        record
        for record in records
        if record.record_kind == "proposal_decision"
        and record.payload.get("proposal_id") == str(proposal_id)
        and int(str(record.payload.get("version", 0))) == current_version
    ]
    status = str(decisions[-1].payload["decision"]) if decisions else str(proposal.status.value)
    return {
        "id": str(proposal_id),
        "status": status,
        "riskClass": reference.payload["risk_class"],
        "policyDecision": reference.payload["policy_decision"],
        "current": _proposal_version(current),
        "previous": _proposal_version(previous) if previous is not None else None,
        "approvedBy": (
            decisions[-1].payload.get("approver_id") if decisions and status == "approved" else None
        ),
    }


def _proposal_version(version: ProposalVersion) -> dict[str, object]:
    payload = json.loads(str(version.canonical_payload))
    return {
        "version": int(version.version),
        "recipient": payload["to"],
        "subject": payload["subject"],
        "body": payload["body"],
        "attachmentIds": [str(identifier) for identifier in version.attachment_artifact_ids],
        "digest": f"sha256:{version.canonical_payload_sha256}",
        "createdLabel": _relative(version.created_at),
    }


def _commands(events: Sequence[StoredEvent]) -> list[dict[str, object]]:
    commands: list[dict[str, object]] = []
    for event in reversed(events):
        if (
            event.event_type
            not in {
                "operator.message_applied",
                "run.redirected",
                "run.status_changed",
            }
            or event.actor_id != "operator"
        ):
            continue
        mode = str(event.payload.get("mode", "queue"))
        commands.append(
            {
                "id": str(event.payload.get("command_id", event.event_id)),
                "mode": mode if mode in {"queue", "redirect"} else "queue",
                "text": str(event.payload.get("body", event.payload.get("summary", event.summary))),
                "status": "applied",
                "createdLabel": _relative(event.created_at),
            }
        )
    return commands
