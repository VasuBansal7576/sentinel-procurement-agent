"""Deterministic credential-free executor for production RuntimeActivities."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from decimal import Decimal
from functools import partial
from typing import Any, cast
from uuid import UUID, uuid4

from temporalio.exceptions import ApplicationError

from sentinel_api.artifacts import generate_artifact_set
from sentinel_api.domain import (
    Candidate,
    EvidenceObservation,
    Money,
    RequestRevision,
    Supplier,
    utc_now,
)
from sentinel_api.evaluation import (
    CandidateEvaluation,
    RankingResult,
    evaluate_candidate,
    rank_candidates,
)
from sentinel_api.integration.brokers import ApprovalBrokerAdapter, await_result
from sentinel_api.integration.demo import DemoProfile
from sentinel_api.integration.models import IntegrationRecord
from sentinel_api.integration.planner import deterministic_id
from sentinel_api.integration.repository import IntegrationRepository
from sentinel_api.persistence.models import EventDraft
from sentinel_api.persistence.protocols import EventStore
from sentinel_api.research import (
    InMemorySnapshotStore,
    UntrustedContent,
    VerifiedObservation,
    build_verified_observation,
)
from sentinel_api.workflows.models import ChildActivityInput, ProducedWork, WorkExecution


class CredentialFreeWorkExecutor:
    """Exercise real modules while keeping every source and effect local."""

    def __init__(
        self,
        *,
        records: IntegrationRepository,
        event_store: EventStore,
        proposal_broker: ApprovalBrokerAdapter,
        demo_profile: DemoProfile | None = None,
    ) -> None:
        self._records = records
        self._event_store = event_store
        self._proposal_broker = proposal_broker
        self._demo_profile = demo_profile or DemoProfile()

    async def __call__(self, request: ChildActivityInput) -> WorkExecution:
        if request.work_item.kind != "end_to_end":
            raise ValueError(f"unsupported credential-free work kind: {request.work_item.kind}")
        run_id = UUID(request.parent_run_id)
        input_ref = UUID(request.work_item.input_ref.removeprefix("record://"))
        loaded = await self._step(
            request,
            "request.load",
            lambda: self._request_record(run_id, input_ref, request),
        )
        if not isinstance(loaded, IntegrationRecord):
            raise KeyError("typed request input record does not exist")
        revision = RequestRevision.model_validate(loaded.payload["revision"])
        line_item = revision.lots[0].line_items[0]

        candidates: list[Candidate] = []
        observations: list[EvidenceObservation] = []
        snapshot_store = InMemorySnapshotStore()
        candidate_specs = (
            ("Northstar", Decimal("24"), Decimal("760"), True),
            ("Blue River", Decimal("29"), Decimal("840"), True),
            ("Cedar Works", Decimal("42"), Decimal("690"), True),
        )
        for position, (supplier_name, lead_time, unit_price, available) in enumerate(
            candidate_specs,
            start=1,
        ):
            construct_candidate = partial(
                Candidate,
                id=deterministic_id(run_id, f"candidate:{position}"),
                request_revision_id=revision.id,
                lot_id=revision.lots[0].id,
                supplier=Supplier(
                    id=deterministic_id(run_id, f"supplier:{position}"),
                    legal_name=f"{supplier_name} Supply",
                    website=f"https://supplier-{position}.example.test",
                    country_code="US",
                ),
                offering_name=f"{line_item.name} option {position}",
                source_url=(
                    f"https://supplier-{position}.example.test/catalog/"
                    f"{deterministic_id(run_id, f'page:{position}')}"
                ),
                quoted_price=Money(amount=unit_price, currency="USD"),
                attributes={"description": line_item.description},
            )
            candidate: Candidate = await self._step(
                request,
                f"candidate.{position}.construct",
                construct_candidate,
            )
            candidates.append(candidate)
            exact_values = {
                "availability": "Available: yes" if available else "Available: no",
                "lead_time": f"Lead time: {lead_time} days",
                "unit_price": f"Unit price: USD {unit_price}",
            }
            body = (
                f"{candidate.supplier.legal_name}\n"
                f"Offering: {candidate.offering_name}\n" + "\n".join(exact_values.values())
            ).encode()
            content = UntrustedContent.from_body(
                url=candidate.source_url,
                body=body,
                media_type="text/plain; charset=utf-8",
            )
            persist_snapshot = partial(
                snapshot_store.put,
                run_id=run_id,
                request_revision_id=revision.id,
                producer="sentinel.credential-free-research/1.0",
                content=content,
            )
            snapshot = await self._step(
                request,
                f"candidate.{position}.snapshot",
                persist_snapshot,
            )
            for requirement_key, value, unit in (
                ("availability", available, None),
                ("lead_time", lead_time, "day"),
                ("unit_price", unit_price, "USD"),
            ):
                extract = partial(
                    build_verified_observation,
                    snapshot=snapshot,
                    request_revision_id=revision.id,
                    candidate_id=candidate.id,
                    requirement_key=requirement_key,
                    value=value,
                    exact_text=exact_values[requirement_key],
                    extractor_version="credential-free-extractor/1.0",
                    confidence=1,
                    evidence_type="supplier_page",
                    normalized_unit=unit,
                )
                verified: VerifiedObservation = await self._step(
                    request,
                    f"candidate.{position}.extract.{requirement_key}",
                    extract,
                )
                observations.append(verified.observation)

        candidate_record = await self._put_json(
            request,
            "candidates.persist",
            "candidates",
            {"candidates": [candidate.model_dump(mode="json") for candidate in candidates]},
        )
        evidence_record = await self._put_json(
            request,
            "evidence.persist",
            "evidence",
            {"observations": [observation.model_dump(mode="json") for observation in observations]},
        )
        evaluations: list[CandidateEvaluation] = []
        for position, candidate in enumerate(candidates, start=1):
            evaluate = partial(
                evaluate_candidate,
                candidate,
                line_item.requirements,
                tuple(observations),
                as_of=utc_now(),
            )
            evaluation = await self._step(
                request,
                f"candidate.{position}.evaluate",
                evaluate,
            )
            evaluations.append(evaluation)
        ranking: RankingResult = await self._step(
            request,
            "candidates.rank",
            lambda: rank_candidates(evaluations),
        )
        evaluation_record = await self._put_json(
            request,
            "evaluation.persist",
            "evaluation",
            {
                "recommended_candidate_id": (
                    str(ranking.recommended_candidate_id)
                    if ranking.recommended_candidate_id
                    else None
                ),
                "candidates": [
                    {
                        "rank": ranked.rank,
                        "candidate_id": str(ranked.evaluation.candidate.id),
                        "eligible": ranked.evaluation.eligible,
                        "score": str(ranked.evaluation.score),
                        "coverage": str(ranked.evaluation.coverage.percent),
                        "failed_mandatory": list(ranked.evaluation.failed_mandatory_keys),
                        "unresolved_mandatory": list(ranked.evaluation.unresolved_mandatory_keys),
                        "requirements": [
                            {
                                "key": item.requirement.key,
                                "status": item.status.value,
                                "value": _json_scalar(item.value),
                                "observation_ids": [
                                    str(identifier) for identifier in item.observation_ids
                                ],
                            }
                            for item in ranked.evaluation.requirements
                        ],
                    }
                    for ranked in ranking.candidates
                ],
            },
        )
        generated = await self._step(
            request,
            "artifacts.generate",
            lambda: generate_artifact_set(revision, ranking),
        )
        artifact_records: list[IntegrationRecord] = []
        for position, artifact in enumerate(generated, start=1):
            artifact_id = uuid4()
            artifact_record = IntegrationRecord(
                run_id=run_id,
                record_ref=artifact_id,
                record_kind="artifact",
                payload={
                    "kind": artifact.kind.value,
                    "version": 1,
                    "status": "ready",
                },
                content=artifact.content,
                filename=artifact.filename,
                media_type=artifact.media_type,
                content_sha256=artifact.sha256,
            )
            artifact_records.append(
                await self._step(
                    request,
                    f"artifact.{position}.persist",
                    partial(self._records.put, artifact_record),
                )
            )
        recipient = "procurement-demo@example.test"
        proposal_payload = {
            "to": recipient,
            "subject": f"Request for quotation — {line_item.name}",
            "body": (
                f"Please quote {line_item.quantity.value} {line_item.quantity.unit} "
                f"of {line_item.name}. Confirm availability and lead time."
            ),
        }
        proposal_result = await self._step(
            request,
            "proposal.prepare",
            lambda: await_result(
                self._proposal_broker.create_proposal(
                    run_id=run_id,
                    request_revision_id=revision.id,
                    action_type="email.send",
                    payload=proposal_payload,
                    attachment_artifact_ids=tuple(record.record_ref for record in artifact_records),
                    attachment_sha256=tuple(
                        cast(str, record.content_sha256) for record in artifact_records
                    ),
                )
            ),
        )
        proposal, version = proposal_result
        proposal_id = proposal.id
        proposal_record = await self._put_json(
            request,
            "proposal.persist",
            "proposal_ref",
            {
                "proposal_id": str(proposal_id),
                "current_version": int(version.version),
                "status": str(proposal.status.value),
                "risk_class": "external_send",
                "policy_decision": "Exact approval required; fake provider only",
            },
            record_ref=proposal_id,
        )
        output_ref = deterministic_id(
            run_id,
            f"execution:{request.work_item.work_item_id}:{request.attempt}",
        )
        await self._records.put(
            IntegrationRecord(
                run_id=run_id,
                record_ref=output_ref,
                record_kind="execution",
                payload={
                    "candidate_ref": str(candidate_record.record_ref),
                    "evidence_ref": str(evidence_record.record_ref),
                    "evaluation_ref": str(evaluation_record.record_ref),
                    "artifact_refs": [str(record.record_ref) for record in artifact_records],
                    "proposal_ref": str(proposal_record.record_ref),
                },
            )
        )
        return WorkExecution(
            summary=(
                f"Compared {len(candidates)} candidates and generated "
                f"{len(artifact_records)} artifacts without credentials"
            ),
            output_ref=f"record://{output_ref}",
            products=tuple(
                ProducedWork(
                    product_id=str(
                        deterministic_id(
                            run_id,
                            f"product:{key}:{request.request_revision_number}",
                        )
                    ),
                    output_key=key,
                    kind=kind,
                    request_revision_number=request.request_revision_number,
                    policy_revision=request.policy_revision,
                    depends_on=request.work_item.depends_on,
                )
                for key, kind in (
                    ("evidence:verified", "evidence"),
                    ("evaluation:ranking", "evaluation"),
                    ("artifact:deliverables", "artifact"),
                    ("proposal:rfq", "proposal"),
                )
            ),
        )

    async def _put_json(
        self,
        request: ChildActivityInput,
        step: str,
        kind: str,
        payload: dict[str, object],
        *,
        record_ref: UUID | None = None,
    ) -> IntegrationRecord:
        run_id = UUID(request.parent_run_id)
        target_ref = record_ref or deterministic_id(
            run_id,
            f"{kind}:{request.request_revision_number}:{request.attempt}",
        )
        return await self._step(
            request,
            step,
            lambda: self._records.put(
                IntegrationRecord(
                    run_id=run_id,
                    record_ref=target_ref,
                    record_kind=kind,
                    payload=payload,
                )
            ),
        )

    async def _step(
        self,
        request: ChildActivityInput,
        step: str,
        operation: Callable[[], object],
    ) -> Any:
        run_id = UUID(request.parent_run_id)
        if self._demo_profile.enabled and self._demo_profile.step_delay_seconds:
            await asyncio.sleep(self._demo_profile.step_delay_seconds)
        base_key = (
            f"executor:{request.work_item.work_item_id}:"
            f"attempt:{request.attempt}:revision:{request.request_revision_number}:{step}"
        )
        await self._event_store.append_event(
            run_id,
            EventDraft(
                event_type="tool.started",
                status="running",
                summary=f"Started {step}",
                payload={
                    "tool": step,
                    "work_item_id": request.work_item.work_item_id,
                    "attempt": request.attempt,
                },
                work_item_id=UUID(request.work_item.work_item_id),
                actor_id=request.work_item.subagent_id,
                idempotency_key=f"{base_key}:started",
            ),
        )
        if (
            self._demo_profile.enabled
            and self._demo_profile.failure_step == step
            and request.attempt == 1
        ):
            raise ApplicationError(
                f"Demo browser/tool failure at {step}; retry from the durable checkpoint",
                type="transient",
            )
        result = await await_result(operation())
        await self._event_store.append_event(
            run_id,
            EventDraft(
                event_type="tool.completed",
                status="completed",
                summary=f"Completed {step}",
                payload={
                    "tool": step,
                    "work_item_id": request.work_item.work_item_id,
                    "attempt": request.attempt,
                },
                work_item_id=UUID(request.work_item.work_item_id),
                actor_id=request.work_item.subagent_id,
                idempotency_key=f"{base_key}:completed",
            ),
        )
        return result

    async def _request_record(
        self,
        run_id: UUID,
        input_ref: UUID,
        request: ChildActivityInput,
    ) -> IntegrationRecord | None:
        if request.request_revision_number == 1:
            return await self._records.get(run_id, input_ref)
        for record in reversed(await self._records.list(run_id)):
            if record.record_kind not in {
                "request_revision",
                "request_revision_prepared",
            }:
                continue
            revision = record.payload.get("revision")
            if isinstance(revision, dict) and revision.get("id") == request.request_revision_id:
                return record
        return None


def _json_scalar(value: object) -> object:
    if isinstance(value, Decimal):
        return str(value)
    return value
