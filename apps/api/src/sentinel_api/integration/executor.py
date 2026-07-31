"""Procurement work executor: live Agent-Reach research by default, fake for tests."""

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
    AutonomyMode,
    Candidate,
    EvidenceObservation,
    RequestRevision,
    autonomy_policy_decision,
    utc_now,
)
from sentinel_api.domain.common import ScalarValue
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
from sentinel_api.research.agent_reach import (
    AgentReachResearchClient,
    FakeResearchClient,
    LiveResearchClient,
    discover_sources,
)
from sentinel_api.research.discovery import (
    candidate_from_source,
    ensure_span_in_page,
    extract_facts,
)
from sentinel_api.workflows.models import ChildActivityInput, ProducedWork, WorkExecution


class CredentialFreeWorkExecutor:
    """Run the procurement pipeline with real or fake research adapters."""

    def __init__(
        self,
        *,
        records: IntegrationRepository,
        event_store: EventStore,
        proposal_broker: ApprovalBrokerAdapter,
        demo_profile: DemoProfile | None = None,
        controlled_recipient: str = "procurement-demo@example.test",
        research_client: LiveResearchClient | None = None,
        research_mode: str = "fake",
    ) -> None:
        self._records = records
        self._event_store = event_store
        self._proposal_broker = proposal_broker
        self._demo_profile = demo_profile or DemoProfile()
        self._controlled_recipient = controlled_recipient
        self._research_mode = research_mode
        if research_client is not None:
            self._research = research_client
        elif research_mode == "agent_reach":
            self._research = AgentReachResearchClient()
        else:
            self._research = FakeResearchClient()

    async def __call__(self, request: ChildActivityInput) -> WorkExecution:
        if request.work_item.kind != "end_to_end":
            raise ValueError(f"unsupported work kind: {request.work_item.kind}")
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
        autonomy = _autonomy_from_record(loaded)
        raw_intake = loaded.payload.get("intake")
        intake = raw_intake if isinstance(raw_intake, dict) else {}
        item_name = str(intake.get("item_name") or line_item.name)
        description = str(intake.get("description") or line_item.description)

        sources = await self._step(
            request,
            "research.search",
            lambda: discover_sources(
                self._research,
                item_name=item_name,
                description=description,
                limit=5,
            ),
        )

        candidates: list[Candidate] = []
        observations: list[EvidenceObservation] = []
        snapshot_store = InMemorySnapshotStore()
        producer = (
            "sentinel.agent-reach-research/1.0"
            if self._research_mode == "agent_reach"
            else "sentinel.fake-research/1.0"
        )

        for position, source in enumerate(sources, start=1):
            facts = extract_facts(source, item_name=item_name)
            construct_candidate = partial(
                candidate_from_source,
                run_id=run_id,
                position=position,
                request_revision_id=revision.id,
                lot_id=revision.lots[0].id,
                item_name=item_name,
                description=description,
                source=source,
                facts=facts,
            )
            candidate: Candidate = await self._step(
                request,
                f"candidate.{position}.construct",
                construct_candidate,
            )
            candidates.append(candidate)

            evidence_lines = [
                facts.availability_text,
                facts.lead_time_text,
            ]
            if facts.unit_price_text:
                evidence_lines.append(facts.unit_price_text)
            page_body = ensure_span_in_page(source.page_text, "\n".join(evidence_lines))
            # Also ensure each individual span exists for extractors.
            for line in evidence_lines:
                page_body = ensure_span_in_page(page_body, line)

            content = UntrustedContent.from_body(
                url=source.url,
                body=page_body.encode("utf-8", errors="replace"),
                media_type="text/markdown; charset=utf-8",
            )
            persist_snapshot = partial(
                snapshot_store.put,
                run_id=run_id,
                request_revision_id=revision.id,
                producer=producer,
                content=content,
            )
            snapshot = await self._step(
                request,
                f"candidate.{position}.snapshot",
                persist_snapshot,
            )

            extract_jobs: list[tuple[str, ScalarValue, str | None, str]] = [
                ("availability", facts.available, None, facts.availability_text),
                ("lead_time", facts.lead_time_days, "day", facts.lead_time_text),
            ]
            if facts.unit_price is not None and facts.unit_price_text:
                extract_jobs.append(
                    ("unit_price", facts.unit_price, "USD", facts.unit_price_text),
                )
            for requirement_key, value, unit, exact_text in extract_jobs:
                extract = partial(
                    build_verified_observation,
                    snapshot=snapshot,
                    request_revision_id=revision.id,
                    candidate_id=candidate.id,
                    requirement_key=requirement_key,
                    value=value,
                    exact_text=exact_text,
                    extractor_version=f"{producer}-extractor",
                    confidence=0.7 if self._research_mode == "agent_reach" else 1.0,
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
            {
                "observations": [
                    observation.model_dump(mode="json") for observation in observations
                ],
                "research_mode": self._research_mode,
            },
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
                "research_mode": self._research_mode,
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
        proposal_record: IntegrationRecord | None = None
        product_specs: tuple[tuple[str, str], ...]
        research_note = (
            "public web sources via Agent Reach (Exa search + Jina Reader)"
            if self._research_mode == "agent_reach"
            else "deterministic local research fixtures"
        )
        if autonomy is AutonomyMode.RESEARCH_ONLY:
            await self._step(
                request,
                "proposal.suppress",
                lambda: {
                    "autonomy_mode": autonomy.value,
                    "reason": "Research only: external RFQ contact is disabled",
                },
            )
            summary = (
                f"Compared {len(candidates)} candidates from {research_note} and "
                f"generated {len(artifact_records)} artifacts under research-only autonomy"
            )
            product_specs = (
                ("evidence:verified", "evidence"),
                ("evaluation:ranking", "evaluation"),
                ("artifact:deliverables", "artifact"),
            )
        else:
            recipient = self._controlled_recipient
            top = ranking.recommended_candidate_id
            top_name = next(
                (candidate.offering_name for candidate in candidates if candidate.id == top),
                item_name,
            )
            proposal_payload = {
                "to": recipient,
                "subject": f"Request for quotation — {item_name}",
                "body": (
                    f"Please quote {line_item.quantity.value} {line_item.quantity.unit} "
                    f"of {item_name}.\n\n"
                    f"Need: {description}\n"
                    f"Working recommendation from public sources: {top_name}\n"
                    f"Research mode: {research_note}. Confirm availability and lead time."
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
                        attachment_artifact_ids=tuple(
                            record.record_ref for record in artifact_records
                        ),
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
                    "autonomy_mode": autonomy.value,
                    "research_mode": self._research_mode,
                    "policy_decision": (
                        f"{autonomy_policy_decision(autonomy)}; approval never auto-sends"
                    ),
                },
                record_ref=proposal_id,
            )
            summary = (
                f"Compared {len(candidates)} candidates from {research_note} and "
                f"generated {len(artifact_records)} artifacts"
            )
            product_specs = (
                ("evidence:verified", "evidence"),
                ("evaluation:ranking", "evaluation"),
                ("artifact:deliverables", "artifact"),
                ("proposal:rfq", "proposal"),
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
                    "proposal_ref": (
                        str(proposal_record.record_ref) if proposal_record is not None else None
                    ),
                    "autonomy_mode": autonomy.value,
                    "research_mode": self._research_mode,
                },
            )
        )
        return WorkExecution(
            summary=summary,
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
                for key, kind in product_specs
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


def _autonomy_from_record(record: IntegrationRecord) -> AutonomyMode:
    raw = record.payload.get("autonomy_mode")
    if raw is None:
        intake = record.payload.get("intake")
        if isinstance(intake, dict):
            raw = intake.get("autonomy_mode")
    if raw is None:
        return AutonomyMode.ASK_BEFORE_EXTERNAL
    try:
        return AutonomyMode(str(raw))
    except ValueError:
        return AutonomyMode.ASK_BEFORE_EXTERNAL
