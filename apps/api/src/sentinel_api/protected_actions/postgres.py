"""PostgreSQL-backed protected-action broker with atomic permit consumption."""

import hashlib
from datetime import datetime, timedelta
from typing import cast
from uuid import UUID

from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from sentinel_api.domain import (
    ActionIntent,
    ActionOutcomeState,
    ApprovalPermit,
    EffectivePolicy,
    Proposal,
    ProposalVersion,
    RiskClass,
    utc_now,
)
from sentinel_api.domain.actions import ProposalStatus
from sentinel_api.protected_actions.broker import (
    ApprovalBroker,
    AuthorizationError,
    AuthorizedAction,
    CommitContext,
    PolicyDecision,
    ProposalDiff,
)

Row = dict[str, object]


def _datetime(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"expected datetime, got {type(value).__name__}")
    return value


def _uuid(value: object) -> UUID:
    if isinstance(value, UUID):
        return value
    return UUID(str(value))


def _proposal(row: Row) -> Proposal:
    return Proposal(
        id=_uuid(row["proposal_id"]),
        run_id=_uuid(row["run_id"]),
        request_revision_id=_uuid(row["request_revision_id"]),
        current_version=int(cast(int, row["current_version"])),
        status=ProposalStatus(str(row["status"])),
    )


def _version(row: Row) -> ProposalVersion:
    return ProposalVersion(
        proposal_id=_uuid(row["proposal_id"]),
        version=int(cast(int, row["version"])),
        action_type=str(row["action_type"]),
        canonical_payload=str(row["canonical_payload"]),
        canonical_payload_sha256=str(row["canonical_payload_sha256"]),
        attachment_artifact_ids=tuple(
            _uuid(value) for value in cast(list[object], row["attachment_artifact_ids"])
        ),
        attachment_sha256=tuple(
            str(value) for value in cast(list[object], row["attachment_sha256"])
        ),
        created_at=_datetime(row["created_at"]),
    )


def _permit(row: Row) -> ApprovalPermit:
    consumed_at = row["consumed_at"]
    return ApprovalPermit(
        id=_uuid(row["permit_id"]),
        proposal_id=_uuid(row["proposal_id"]),
        proposal_version=int(cast(int, row["proposal_version"])),
        action_type=str(row["action_type"]),
        canonical_payload_sha256=str(row["canonical_payload_sha256"]),
        attachment_sha256=tuple(
            str(value) for value in cast(list[object], row["attachment_sha256"])
        ),
        policy_decision_id=_uuid(row["policy_decision_id"]),
        organization_policy_id=_uuid(row["organization_policy_id"]),
        organization_revision=int(cast(int, row["organization_revision"])),
        risk_class=RiskClass(str(row["risk_class"])),
        approver_id=_uuid(row["approver_id"]),
        approved_at=_datetime(row["approved_at"]),
        expires_at=_datetime(row["expires_at"]),
        nonce=_uuid(row["nonce"]),
        consumed_at=None if consumed_at is None else _datetime(consumed_at),
    )


class PostgresApprovalBroker:
    """Durable broker whose approval and consumption transitions are row-locked."""

    def __init__(self, pool: AsyncConnectionPool[AsyncConnection[Row]]) -> None:
        self._pool = pool

    @classmethod
    def from_url(
        cls,
        database_url: str,
        *,
        min_size: int = 1,
        max_size: int = 10,
        open_pool: bool = False,
    ) -> "PostgresApprovalBroker":
        conninfo = database_url.replace("postgresql+psycopg://", "postgresql://", 1)
        pool: AsyncConnectionPool[AsyncConnection[Row]] = AsyncConnectionPool(
            conninfo,
            min_size=min_size,
            max_size=max_size,
            open=open_pool,
            kwargs={"row_factory": dict_row},
        )
        return cls(pool)

    async def open(self) -> None:
        await self._pool.open()
        await self._pool.wait()

    async def close(self) -> None:
        await self._pool.close()

    async def create_proposal(
        self,
        *,
        run_id: UUID,
        request_revision_id: UUID,
        action_type: str,
        payload: object,
        attachment_artifact_ids: tuple[UUID, ...] = (),
        attachment_sha256: tuple[str, ...] = (),
    ) -> tuple[Proposal, ProposalVersion]:
        proposal = Proposal(
            run_id=run_id,
            request_revision_id=request_revision_id,
            status=ProposalStatus.PENDING_APPROVAL,
        )
        version = ApprovalBroker._make_version(
            proposal_id=proposal.id,
            version=1,
            action_type=action_type,
            payload=payload,
            attachment_artifact_ids=attachment_artifact_ids,
            attachment_sha256=attachment_sha256,
        )
        async with self._pool.connection() as connection, connection.transaction():
            await connection.execute(
                """
                INSERT INTO sentinel.proposals (
                    proposal_id, run_id, request_revision_id, current_version, status
                )
                VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    proposal.id,
                    proposal.run_id,
                    proposal.request_revision_id,
                    proposal.current_version,
                    proposal.status.value,
                ),
            )
            await self._insert_version(connection, version)
        return proposal, version

    async def edit_proposal(
        self,
        proposal_id: UUID,
        *,
        payload: object,
        attachment_artifact_ids: tuple[UUID, ...] = (),
        attachment_sha256: tuple[str, ...] = (),
    ) -> tuple[Proposal, ProposalVersion, ProposalDiff]:
        async with self._pool.connection() as connection, connection.transaction():
            proposal = await self._get_proposal(connection, proposal_id, lock=True)
            previous = await self._get_version(
                connection,
                proposal_id,
                proposal.current_version,
            )
            version = ApprovalBroker._make_version(
                proposal_id=proposal_id,
                version=proposal.current_version + 1,
                action_type=previous.action_type,
                payload=payload,
                attachment_artifact_ids=attachment_artifact_ids,
                attachment_sha256=attachment_sha256,
            )
            await self._insert_version(connection, version)
            cursor = await connection.execute(
                """
                UPDATE sentinel.proposals
                SET current_version = %s,
                    status = %s,
                    updated_at = clock_timestamp()
                WHERE proposal_id = %s
                RETURNING *
                """,
                (version.version, ProposalStatus.PENDING_APPROVAL.value, proposal_id),
            )
            updated_row = await cursor.fetchone()
            if updated_row is None:
                raise AuthorizationError("proposal does not exist")
            updated = _proposal(updated_row)
            return (
                updated,
                version,
                ProposalDiff(
                    proposal_id=proposal_id,
                    from_version=previous.version,
                    to_version=version.version,
                    changed_fields=ApprovalBroker._changed_fields(previous, version),
                    attachments_changed=previous.attachment_sha256 != version.attachment_sha256,
                ),
            )

    async def issue_permit(
        self,
        *,
        proposal_id: UUID,
        proposal_version: int,
        expected_payload_sha256: str,
        expected_attachment_sha256: tuple[str, ...],
        policy_decision: PolicyDecision,
        effective_policy: EffectivePolicy,
        approver_id: UUID,
        ttl: timedelta = timedelta(minutes=15),
        now: datetime | None = None,
    ) -> ApprovalPermit:
        issued_at = now or utc_now()
        async with self._pool.connection() as connection, connection.transaction():
            proposal = await self._get_proposal(connection, proposal_id, lock=True)
            version = await self._get_version(connection, proposal_id, proposal_version)
            ApprovalBroker._validate_policy_decision(
                policy_decision,
                effective_policy,
                expected_action=ApprovalBroker._policy_action_for(version),
            )
            if proposal.current_version != proposal_version:
                raise AuthorizationError("only the current proposal version can be approved")
            if version.canonical_payload_sha256 != expected_payload_sha256:
                raise AuthorizationError("approval preview does not match canonical payload")
            if version.attachment_sha256 != expected_attachment_sha256:
                raise AuthorizationError("approval preview does not match attachment digests")
            ApprovalBroker._validate_payload_policy(version, effective_policy)
            permit = ApprovalPermit(
                proposal_id=proposal_id,
                proposal_version=proposal_version,
                action_type=version.action_type,
                canonical_payload_sha256=version.canonical_payload_sha256,
                attachment_sha256=version.attachment_sha256,
                policy_decision_id=policy_decision.id,
                organization_policy_id=policy_decision.organization_policy_id,
                organization_revision=policy_decision.organization_revision,
                risk_class=RiskClass.EXTERNAL_SEND,
                approver_id=approver_id,
                approved_at=issued_at,
                expires_at=issued_at + ttl,
            )
            await connection.execute(
                """
                INSERT INTO sentinel.policy_decisions (
                    policy_decision_id, proposal_id, proposal_version, action,
                    allowed, reason, organization_policy_id,
                    organization_revision, decided_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    policy_decision.id,
                    proposal_id,
                    proposal_version,
                    policy_decision.action.value,
                    policy_decision.allowed,
                    policy_decision.reason,
                    policy_decision.organization_policy_id,
                    policy_decision.organization_revision,
                    policy_decision.decided_at,
                ),
            )
            await connection.execute(
                """
                INSERT INTO sentinel.approval_permits (
                    permit_id, proposal_id, proposal_version, action_type,
                    canonical_payload_sha256, attachment_sha256,
                    policy_decision_id, organization_policy_id,
                    organization_revision, risk_class, approver_id,
                    approved_at, expires_at, nonce, consumed_at
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s
                )
                """,
                (
                    permit.id,
                    permit.proposal_id,
                    permit.proposal_version,
                    permit.action_type,
                    permit.canonical_payload_sha256,
                    list(permit.attachment_sha256),
                    permit.policy_decision_id,
                    permit.organization_policy_id,
                    permit.organization_revision,
                    permit.risk_class.value,
                    permit.approver_id,
                    permit.approved_at,
                    permit.expires_at,
                    permit.nonce,
                    permit.consumed_at,
                ),
            )
            await connection.execute(
                """
                UPDATE sentinel.proposals
                SET status = %s, updated_at = clock_timestamp()
                WHERE proposal_id = %s
                """,
                (ProposalStatus.APPROVED.value, proposal_id),
            )
            return permit

    async def authorize_and_consume(
        self,
        *,
        permit_id: UUID,
        effective_policy: EffectivePolicy,
        context: CommitContext,
        now: datetime | None = None,
    ) -> AuthorizedAction:
        authorized_at = now or utc_now()
        async with self._pool.connection() as connection, connection.transaction():
            cursor = await connection.execute(
                """
                SELECT *
                FROM sentinel.approval_permits
                WHERE permit_id = %s
                FOR UPDATE
                """,
                (permit_id,),
            )
            permit_row = await cursor.fetchone()
            if permit_row is None:
                raise AuthorizationError("approval permit does not exist")
            permit = _permit(permit_row)
            if permit.consumed_at is not None:
                raise AuthorizationError("approval permit has already been consumed")
            if authorized_at >= permit.expires_at:
                raise AuthorizationError("approval permit has expired")
            if "protected_action.execute" not in context.capabilities:
                raise AuthorizationError("executor lacks protected-action capability")
            if context.organization_policy_id != effective_policy.organization_policy_id:
                raise AuthorizationError("commit context belongs to another organization policy")
            if context.organization_revision != effective_policy.organization_revision:
                raise AuthorizationError("commit context uses a stale policy revision")
            if permit.organization_policy_id != effective_policy.organization_policy_id:
                raise AuthorizationError("approval permit belongs to another organization policy")
            if permit.organization_revision != effective_policy.organization_revision:
                raise AuthorizationError("approval permit was issued under a stale policy revision")
            proposal = await self._get_proposal(
                connection,
                permit.proposal_id,
                lock=True,
            )
            if proposal.current_version != permit.proposal_version:
                raise AuthorizationError("proposal was edited after approval")
            if context.proposal_version != permit.proposal_version:
                raise AuthorizationError("commit context proposal version does not match permit")
            if proposal.status is not ProposalStatus.APPROVED:
                raise AuthorizationError("proposal is not approved")
            version = await self._get_version(
                connection,
                permit.proposal_id,
                permit.proposal_version,
            )
            if version.canonical_payload_sha256 != permit.canonical_payload_sha256:
                raise AuthorizationError("approved payload digest no longer matches")
            if context.canonical_payload_sha256 != permit.canonical_payload_sha256:
                raise AuthorizationError("commit context payload digest does not match permit")
            if version.attachment_sha256 != permit.attachment_sha256:
                raise AuthorizationError("approved attachment digests no longer match")
            if context.attachment_sha256 != permit.attachment_sha256:
                raise AuthorizationError("commit context attachment digests do not match permit")
            ApprovalBroker._validate_payload_policy(version, effective_policy)
            idempotency_material = (
                f"{permit.proposal_id}:{permit.proposal_version}:{permit.nonce}"
            ).encode()
            intent = ActionIntent(
                proposal_id=permit.proposal_id,
                proposal_version=permit.proposal_version,
                permit_id=permit.id,
                idempotency_key=hashlib.sha256(idempotency_material).hexdigest(),
                payload_fingerprint=version.canonical_payload_sha256,
                created_at=authorized_at,
            )
            await connection.execute(
                """
                UPDATE sentinel.approval_permits
                SET consumed_at = %s
                WHERE permit_id = %s AND consumed_at IS NULL
                """,
                (authorized_at, permit.id),
            )
            await connection.execute(
                """
                INSERT INTO sentinel.action_intents (
                    action_intent_id, proposal_id, proposal_version, permit_id,
                    idempotency_key, payload_fingerprint, created_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    intent.id,
                    intent.proposal_id,
                    intent.proposal_version,
                    intent.permit_id,
                    intent.idempotency_key,
                    intent.payload_fingerprint,
                    intent.created_at,
                ),
            )
            await connection.execute(
                """
                INSERT INTO sentinel.action_outcomes (
                    action_intent_id, state, updated_at
                )
                VALUES (%s, %s, %s)
                """,
                (intent.id, ActionOutcomeState.APPROVED.value, authorized_at),
            )
            await connection.execute(
                """
                UPDATE sentinel.proposals
                SET status = %s, updated_at = clock_timestamp()
                WHERE proposal_id = %s
                """,
                (ProposalStatus.AUTHORIZED.value, permit.proposal_id),
            )
            return AuthorizedAction(
                intent=intent,
                canonical_payload=version.canonical_payload,
                permit_nonce=permit.nonce,
            )

    async def get_proposal(self, proposal_id: UUID) -> Proposal:
        async with self._pool.connection() as connection:
            return await self._get_proposal(connection, proposal_id)

    async def get_version(self, proposal_id: UUID, version: int) -> ProposalVersion:
        async with self._pool.connection() as connection:
            return await self._get_version(connection, proposal_id, version)

    @staticmethod
    async def _insert_version(
        connection: AsyncConnection[Row],
        version: ProposalVersion,
    ) -> None:
        await connection.execute(
            """
            INSERT INTO sentinel.proposal_versions (
                proposal_id, version, action_type, canonical_payload,
                canonical_payload_sha256, attachment_artifact_ids,
                attachment_sha256, created_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                version.proposal_id,
                version.version,
                version.action_type,
                version.canonical_payload,
                version.canonical_payload_sha256,
                list(version.attachment_artifact_ids),
                list(version.attachment_sha256),
                version.created_at,
            ),
        )

    @staticmethod
    async def _get_proposal(
        connection: AsyncConnection[Row],
        proposal_id: UUID,
        *,
        lock: bool = False,
    ) -> Proposal:
        suffix = " FOR UPDATE" if lock else ""
        cursor = await connection.execute(
            f"SELECT * FROM sentinel.proposals WHERE proposal_id = %s{suffix}",
            (proposal_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            raise AuthorizationError("proposal does not exist")
        return _proposal(row)

    @staticmethod
    async def _get_version(
        connection: AsyncConnection[Row],
        proposal_id: UUID,
        version: int,
    ) -> ProposalVersion:
        cursor = await connection.execute(
            """
            SELECT *
            FROM sentinel.proposal_versions
            WHERE proposal_id = %s AND version = %s
            """,
            (proposal_id, version),
        )
        row = await cursor.fetchone()
        if row is None:
            raise AuthorizationError("proposal version does not exist")
        return _version(row)
