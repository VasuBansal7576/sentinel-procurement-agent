"""Application service for intake, commands, projections, and exact proposals."""

from __future__ import annotations

from typing import cast
from uuid import UUID

from sentinel_api.application.walking_skeleton import CreateRunRequest
from sentinel_api.domain import (
    AutonomyMode,
    OrganizationPolicy,
    Proposal,
    ProposalVersion,
    RequestPolicyOverlay,
    RequestRevision,
    autonomy_label,
    resolve_policy,
)
from sentinel_api.domain.policy import ProtectedAction
from sentinel_api.integration.brokers import ApprovalBrokerAdapter, await_result
from sentinel_api.integration.models import (
    ArtifactDownload,
    AutonomyCommandRequest,
    CommandRequest,
    IntegrationRecord,
    MessageCommandRequest,
    ProposalDecisionRequest,
    ProposalEditRequest,
    RedirectCommandRequest,
)
from sentinel_api.integration.planner import deterministic_id, normalize_intake
from sentinel_api.integration.projections import (
    HONESTY_BANNER,
    operator_run_view,
    resolve_autonomy,
    session_view,
)
from sentinel_api.integration.repository import IntegrationRepository
from sentinel_api.integration.runtime import RuntimeLauncher
from sentinel_api.persistence.models import EventDraft, NewRun
from sentinel_api.persistence.protocols import EventStore
from sentinel_api.protected_actions import PolicyDecision
from sentinel_api.workflows.models import (
    PauseCommand,
    QueueMessageCommand,
    RedirectCommand,
    ResumeCommand,
    RetryWorkCommand,
)


class IntegrationService:
    """Single orchestration seam shared by HTTP, worker, and tests."""

    def __init__(
        self,
        *,
        event_store: EventStore,
        records: IntegrationRepository,
        runtime: RuntimeLauncher,
        proposal_broker: ApprovalBrokerAdapter,
        runtime_disclosure: str = (
            "Deterministic local research and fake email. "
            "Approval records permission only; it never sends."
        ),
        honesty_banner: str = HONESTY_BANNER,
    ) -> None:
        self.event_store = event_store
        self.records = records
        self.runtime = runtime
        self.proposal_broker = proposal_broker
        self.runtime_disclosure = runtime_disclosure
        self.honesty_banner = honesty_banner

    async def create_run(self, request: CreateRunRequest) -> dict[str, object]:
        case, revision, runtime_input, record = normalize_intake(request)
        record = IntegrationRecord(
            run_id=record.run_id,
            record_ref=record.record_ref,
            record_kind=record.record_kind,
            payload={
                **record.payload,
                "autonomy_mode": request.autonomy_mode.value,
            },
            content=record.content,
            filename=record.filename,
            media_type=record.media_type,
            content_sha256=record.content_sha256,
            version=record.version,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )
        await self.event_store.create_run(
            NewRun(
                run_id=record.run_id,
                procurement_case_id=case.id,
                request_revision_id=revision.id,
                policy_revision=1,
                title=case.title,
                status="queued",
                summary="Typed generic procurement request accepted",
            )
        )
        await self.records.put(record)
        await self.records.put(
            IntegrationRecord(
                run_id=record.run_id,
                record_ref=deterministic_id(record.run_id, "autonomy:1"),
                record_kind="autonomy_mode",
                payload={
                    "autonomy_mode": request.autonomy_mode.value,
                    "label": autonomy_label(request.autonomy_mode),
                    "source": "intake",
                },
                version=1,
            )
        )
        await self.event_store.append_event(
            record.run_id,
            EventDraft(
                event_type="request.normalized",
                status="completed",
                summary=(f"Normalized {request.quantity} {request.unit} of {request.item_name}"),
                payload={
                    "request_ref": str(record.record_ref),
                    "request_revision_id": str(revision.id),
                    "request_revision_number": 1,
                    "autonomy_mode": request.autonomy_mode.value,
                },
                payload_ref=f"record://{record.record_ref}",
                idempotency_key="request.normalized:1",
            ),
        )
        await self.event_store.append_event(
            record.run_id,
            EventDraft(
                event_type="operator.autonomy_set",
                status="completed",
                summary=f"Autonomy set to {autonomy_label(request.autonomy_mode)}",
                payload={
                    "autonomy_mode": request.autonomy_mode.value,
                    "source": "intake",
                },
                actor_id="operator",
                idempotency_key="autonomy:intake:1",
            ),
        )
        await self.runtime.start(runtime_input)
        return await self.get_run(record.run_id)

    async def list_sessions(self) -> list[dict[str, object]]:
        summaries = await self.event_store.list_sessions()
        result = []
        for summary in summaries:
            if summary.parent_run_id is not None:
                continue
            records = await self.records.list(summary.run_id)
            result.append(await session_view(summary, records))
        return result

    async def get_run(self, run_id: UUID) -> dict[str, object]:
        summary = await self.event_store.get_run(run_id)
        if summary is None or summary.parent_run_id is not None:
            raise KeyError("run not found")
        records = await self.records.list(run_id)
        projection = await operator_run_view(
            event_store=self.event_store,
            records=records,
            summary=summary,
            proposal_broker=self.proposal_broker,
        )
        projection["runtimeDisclosure"] = self.runtime_disclosure
        projection["honestyBanner"] = self.honesty_banner
        return projection

    async def get_work_tree(self, run_id: UUID) -> list[dict[str, object]]:
        projection = await self.get_run(run_id)
        return cast(list[dict[str, object]], projection["workTree"])

    async def control(
        self,
        run_id: UUID,
        action: str,
        body: CommandRequest,
    ) -> dict[str, object]:
        summary = await self.event_store.get_run(run_id)
        if summary is None:
            raise KeyError("run not found")
        if summary.status in {"completed", "completed_with_failures", "failed"}:
            raise ValueError("completed runs cannot accept pause or resume commands")
        if action == "pause":
            await self.runtime.pause(
                run_id,
                PauseCommand(command_id=str(body.command_id), reason=body.reason),
            )
        elif action == "resume":
            await self.runtime.resume(
                run_id,
                ResumeCommand(command_id=str(body.command_id), reason=body.reason),
            )
        else:
            raise ValueError("unsupported run control")
        return await self.get_run(run_id)

    async def queue_message(
        self,
        run_id: UUID,
        body: MessageCommandRequest,
    ) -> dict[str, object]:
        await self.runtime.queue_message(
            run_id,
            QueueMessageCommand(
                command_id=str(body.command_id),
                message_id=str(body.message_id),
                body=body.text,
            ),
        )
        return await self.get_run(run_id)

    async def redirect(
        self,
        run_id: UUID,
        body: RedirectCommandRequest,
    ) -> dict[str, object]:
        command_ref = deterministic_id(run_id, f"redirect-command:{body.command_id}")
        existing_command = await self.records.get(run_id, command_ref)
        if existing_command is not None:
            stored_dependencies = existing_command.payload.get(
                "changed_dependencies",
                (),
            )
            if not isinstance(stored_dependencies, (list, tuple)):
                raise ValueError("stored redirect dependencies are invalid")
            if (
                existing_command.payload.get("text") != body.text
                or tuple(str(item) for item in stored_dependencies) != body.changed_dependencies
            ):
                raise ValueError("command_id cannot be reused with a different redirect")
            next_id = UUID(str(existing_command.payload["request_revision_id"]))
            next_number = int(str(existing_command.payload["request_revision_number"]))
            next_revision = RequestRevision.model_validate(existing_command.payload["revision"])
            base_payload = existing_command.payload["request_payload"]
            if not isinstance(base_payload, dict):
                raise ValueError("stored redirect request payload is invalid")
        else:
            request_records = await self.records.list(run_id)
            current = max(
                (
                    record
                    for record in request_records
                    if record.record_kind in {"request", "request_revision"}
                ),
                key=lambda record: record.version,
            )
            revision = RequestRevision.model_validate(current.payload["revision"])
            next_number = revision.revision_number + 1
            next_id = deterministic_id(run_id, f"request-revision:{next_number}")
            next_revision = revision.model_copy(
                update={
                    "id": next_id,
                    "revision_number": next_number,
                    "previous_revision_id": revision.id,
                    "reason": body.text,
                }
            )
            base_payload = current.payload
            await self.records.put(
                IntegrationRecord(
                    run_id=run_id,
                    record_ref=command_ref,
                    record_kind="redirect_command",
                    payload={
                        "command_id": str(body.command_id),
                        "text": body.text,
                        "changed_dependencies": list(body.changed_dependencies),
                        "request_revision_id": str(next_id),
                        "request_revision_number": next_number,
                        "revision": next_revision.model_dump(mode="json"),
                        "request_payload": base_payload,
                    },
                    version=next_number,
                )
            )
            await self.records.put(
                IntegrationRecord(
                    run_id=run_id,
                    record_ref=deterministic_id(
                        run_id,
                        f"request-revision-prepared:{next_id}",
                    ),
                    record_kind="request_revision_prepared",
                    payload={
                        **base_payload,
                        "revision": next_revision.model_dump(mode="json"),
                    },
                    version=next_number,
                )
            )
        await self.runtime.redirect(
            run_id,
            RedirectCommand(
                command_id=str(body.command_id),
                request_revision_id=str(next_id),
                request_revision_number=next_number,
                changed_dependencies=body.changed_dependencies,
                reason=body.text,
            ),
        )
        await self.records.put(
            IntegrationRecord(
                run_id=run_id,
                record_ref=next_id,
                record_kind="request_revision",
                payload={
                    **base_payload,
                    "revision": next_revision.model_dump(mode="json"),
                },
                version=next_number,
            )
        )
        request_records = await self.records.list(run_id)
        retained = [
            str(record.record_ref)
            for record in request_records
            if record.record_kind in {"evidence", "candidates"}
            and "request:scope" not in body.changed_dependencies
        ]
        invalidated = [
            str(record.record_ref)
            for record in request_records
            if record.record_kind in {"evaluation", "artifact", "proposal_ref"}
        ]
        await self.event_store.append_event(
            run_id,
            EventDraft(
                event_type="integration.selective_reuse",
                status="completed",
                summary="Computed selective reuse for request revision",
                payload={
                    "request_revision_number": next_number,
                    "retained_record_refs": retained,
                    "invalidated_record_refs": invalidated,
                },
                actor_id="operator",
                idempotency_key=f"selective-reuse:{next_number}",
            ),
        )
        return await self.get_run(run_id)

    async def retry_work(
        self,
        run_id: UUID,
        work_id: UUID,
        command_id: UUID,
    ) -> dict[str, object]:
        item = next(
            (
                item
                for item in await self.event_store.list_work_items(run_id)
                if item.work_item_id == work_id
            ),
            None,
        )
        if item is None:
            raise KeyError("work item not found")
        if item.status != "failed" or item.blocker not in {"transient", "rate_limited"}:
            raise ValueError("work item is not in an explicitly safe-to-retry state")
        failed_events = [
            event
            for event in await self.event_store.list_events(run_id, limit=500)
            if event.work_item_id == work_id and event.event_type == "work.failed"
        ]
        if not failed_events:
            raise ValueError("failed work has no durable attempt record")
        failed_attempt = failed_events[-1].payload.get("attempt")
        if failed_attempt is None:
            raise ValueError("failed work has no durable attempt number")
        await self.runtime.retry(
            run_id,
            RetryWorkCommand(
                command_id=str(command_id),
                work_item_id=str(work_id),
                expected_attempt=int(str(failed_attempt)),
                reason="Operator retried from the failed checkpoint",
            ),
        )
        return await self.get_run(run_id)

    async def set_autonomy(
        self,
        run_id: UUID,
        body: AutonomyCommandRequest,
    ) -> dict[str, object]:
        summary = await self.event_store.get_run(run_id)
        if summary is None or summary.parent_run_id is not None:
            raise KeyError("run not found")
        records = await self.records.list(run_id)
        current = resolve_autonomy(records)
        if current is body.autonomy_mode:
            return await self.get_run(run_id)
        # Completed runs may only tighten to research only so residual
        # approval UI can be disabled without reopening external authority.
        if (
            summary.status in {"completed", "completed_with_failures", "failed"}
            and body.autonomy_mode is not AutonomyMode.RESEARCH_ONLY
        ):
            raise ValueError(
                "completed runs can only tighten autonomy to research only"
            )
        next_version = (
            max(
                (
                    record.version
                    for record in records
                    if record.record_kind == "autonomy_mode"
                ),
                default=0,
            )
            + 1
        )
        await self.records.put(
            IntegrationRecord(
                run_id=run_id,
                record_ref=deterministic_id(run_id, f"autonomy:{next_version}"),
                record_kind="autonomy_mode",
                payload={
                    "autonomy_mode": body.autonomy_mode.value,
                    "label": autonomy_label(body.autonomy_mode),
                    "source": "operator",
                    "reason": body.reason,
                    "command_id": str(body.command_id),
                    "previous": current.value,
                },
                version=next_version,
            )
        )
        await self.event_store.append_event(
            run_id,
            EventDraft(
                event_type="operator.autonomy_set",
                status="completed",
                summary=(
                    f"Autonomy changed to {autonomy_label(body.autonomy_mode)}"
                ),
                payload={
                    "autonomy_mode": body.autonomy_mode.value,
                    "previous": current.value,
                    "command_id": str(body.command_id),
                    "reason": body.reason,
                },
                actor_id="operator",
                idempotency_key=f"command:{body.command_id}:autonomy",
            ),
        )
        return await self.get_run(run_id)

    async def edit_proposal(
        self,
        run_id: UUID,
        body: ProposalEditRequest,
    ) -> dict[str, object]:
        records = await self.records.list(run_id)
        if resolve_autonomy(records) is AutonomyMode.RESEARCH_ONLY:
            raise ValueError(
                "research only autonomy disables external RFQ proposals"
            )
        proposal, version = await self._proposal(run_id)
        updated = await await_result(
            self.proposal_broker.edit_proposal(
                proposal.id,
                payload={
                    "to": body.recipient,
                    "subject": body.subject,
                    "body": body.body,
                },
                attachment_artifact_ids=version.attachment_artifact_ids,
                attachment_sha256=version.attachment_sha256,
            )
        )
        _, next_version, _ = updated
        await self.records.put(
            IntegrationRecord(
                run_id=run_id,
                record_ref=deterministic_id(
                    run_id,
                    f"proposal-version:{proposal.id}:{next_version.version}",
                ),
                record_kind="proposal_version",
                payload={
                    "proposal_id": str(proposal.id),
                    "version": next_version.version,
                    "digest": next_version.canonical_payload_sha256,
                },
                version=next_version.version,
            )
        )
        await self.event_store.append_event(
            run_id,
            EventDraft(
                event_type="proposal.edited",
                status="pending_approval",
                summary=f"Created proposal version {next_version.version}",
                payload={
                    "proposal_id": str(proposal.id),
                    "version": next_version.version,
                    "digest": next_version.canonical_payload_sha256,
                },
                actor_id="operator",
                idempotency_key=f"proposal:{proposal.id}:version:{next_version.version}",
            ),
        )
        return await self.get_run(run_id)

    async def decide_proposal(
        self,
        run_id: UUID,
        body: ProposalDecisionRequest,
    ) -> dict[str, object]:
        records = await self.records.list(run_id)
        mode = resolve_autonomy(records)
        if mode is AutonomyMode.RESEARCH_ONLY:
            raise ValueError(
                "research only autonomy disables external RFQ approval"
            )
        proposal, version = await self._proposal(run_id)
        decisions = [
            record
            for record in await self.records.list(
                run_id,
                record_kind="proposal_decision",
            )
            if record.payload.get("proposal_id") == str(proposal.id)
            and int(str(record.payload.get("version", 0))) == version.version
        ]
        if decisions:
            previous = str(decisions[-1].payload["decision"])
            requested = "approved" if body.decision == "approve" else "rejected"
            if previous == requested:
                return await self.get_run(run_id)
            raise ValueError("a decided proposal version must be edited before another decision")
        if body.decision == "approve":
            organization = OrganizationPolicy(
                id=deterministic_id(run_id, "organization-policy"),
                organization_id=deterministic_id(run_id, "organization"),
                protected_actions=frozenset({ProtectedAction.EMAIL_SEND}),
                controlled_recipient="procurement-demo@example.test",
            )
            policy = resolve_policy(
                organization,
                RequestPolicyOverlay(allowed_actions=frozenset({ProtectedAction.EMAIL_SEND})),
            )
            permit = await await_result(
                self.proposal_broker.issue_permit(
                    proposal_id=proposal.id,
                    proposal_version=version.version,
                    expected_payload_sha256=version.canonical_payload_sha256,
                    expected_attachment_sha256=version.attachment_sha256,
                    policy_decision=PolicyDecision(
                        action=ProtectedAction.EMAIL_SEND,
                        allowed=True,
                        reason="Operator approved exact controlled demonstration payload",
                        organization_policy_id=policy.organization_policy_id,
                        organization_revision=policy.organization_revision,
                    ),
                    effective_policy=policy,
                    approver_id=body.approver_id,
                )
            )
            permit_id = str(permit.id)
        else:
            permit_id = None
        decision_ref = deterministic_id(
            run_id,
            f"proposal-decision:{proposal.id}:{version.version}:{body.decision}",
        )
        await self.records.put(
            IntegrationRecord(
                run_id=run_id,
                record_ref=decision_ref,
                record_kind="proposal_decision",
                payload={
                    "proposal_id": str(proposal.id),
                    "version": version.version,
                    "decision": ("approved" if body.decision == "approve" else "rejected"),
                    "approver_id": str(body.approver_id),
                    "permit_id": permit_id,
                    "digest": version.canonical_payload_sha256,
                },
            )
        )
        await self.event_store.append_event(
            run_id,
            EventDraft(
                event_type=f"proposal.{body.decision}d",
                status=f"{body.decision}d",
                summary=f"Proposal version {version.version} {body.decision}d",
                payload={
                    "proposal_id": str(proposal.id),
                    "version": version.version,
                    "digest": version.canonical_payload_sha256,
                    "permit_id": permit_id,
                },
                actor_id=str(body.approver_id),
                idempotency_key=f"proposal-decision:{decision_ref}",
            ),
        )
        return await self.get_run(run_id)

    async def artifact(self, run_id: UUID, artifact_id: UUID) -> ArtifactDownload:
        record = await self.records.get(run_id, artifact_id)
        if (
            record is None
            or record.record_kind != "artifact"
            or record.content is None
            or record.filename is None
            or record.media_type is None
            or record.content_sha256 is None
        ):
            raise KeyError("artifact not found")
        return ArtifactDownload(
            run_id=run_id,
            artifact_id=artifact_id,
            filename=record.filename,
            media_type=record.media_type,
            content_sha256=record.content_sha256,
            content=record.content,
        )

    async def _proposal(self, run_id: UUID) -> tuple[Proposal, ProposalVersion]:
        records = await self.records.list(run_id, record_kind="proposal_ref")
        if not records:
            raise KeyError("proposal not found")
        proposal_id = UUID(str(records[-1].payload["proposal_id"]))
        proposal = await await_result(self.proposal_broker.get_proposal(proposal_id))
        version = await await_result(
            self.proposal_broker.get_version(
                proposal_id,
                proposal.current_version,
            )
        )
        return proposal, version
