"""Provider-neutral contracts for approved email execution."""

from __future__ import annotations

import json
import re
from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from typing import Self
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from sentinel_api.domain import ActionOutcomeState, ContractModel, utc_now

_EMAIL_ADDRESS = re.compile(
    r"^(?=.{3,320}$)[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@"
    r"(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+"
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])$"
)
_PROVIDER_MESSAGE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,498}$")


def normalize_email_address(value: str) -> str:
    """Validate a bare mailbox and normalize only its case-insensitive domain."""

    candidate = value.strip()
    if _EMAIL_ADDRESS.fullmatch(candidate) is None:
        raise ValueError("email address must be a valid bare mailbox")
    local, domain = candidate.rsplit("@", 1)
    return f"{local}@{domain.lower()}"


def validate_provider_message_id(value: str) -> str:
    """Reject provider references that are unsafe to persist or place in a URL path."""

    if _PROVIDER_MESSAGE_ID.fullmatch(value) is None:
        raise ValueError("provider message ID contains unsafe characters")
    return value


class ApprovedEmailPayload(ContractModel):
    """Exact email fields bound by the protected-action approval."""

    to: str
    subject: str = Field(min_length=1, max_length=998)
    body: str = Field(min_length=1, max_length=100_000)

    @field_validator("to")
    @classmethod
    def validate_recipient(cls, value: str) -> str:
        return normalize_email_address(value)

    @field_validator("subject")
    @classmethod
    def reject_subject_control_characters(cls, value: str) -> str:
        if "\r" in value or "\n" in value:
            raise ValueError("email subject cannot contain line breaks")
        return value


class EmailMessage(ContractModel):
    """Provider-neutral message ready for an email provider."""

    sender: str
    recipient: str
    subject: str = Field(min_length=1, max_length=998)
    text_body: str = Field(min_length=1, max_length=100_000)

    @field_validator("sender", "recipient")
    @classmethod
    def validate_mailbox(cls, value: str) -> str:
        return normalize_email_address(value)

    @field_validator("subject")
    @classmethod
    def reject_subject_control_characters(cls, value: str) -> str:
        if "\r" in value or "\n" in value:
            raise ValueError("email subject cannot contain line breaks")
        return value


class EmailDispatchRequest(ContractModel):
    """One payload-bound provider request with a stable idempotency key."""

    action_intent_id: UUID
    idempotency_key: str = Field(min_length=8, max_length=200)
    payload_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    authorized_at: datetime
    message: EmailMessage


class ProviderReceipt(ContractModel):
    """Sanitized proof that a provider accepted the message."""

    provider: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,49}$")
    message_id: str = Field(min_length=1, max_length=500)
    accepted_at: datetime
    status: str = Field(min_length=2, max_length=100)

    @field_validator("message_id")
    @classmethod
    def validate_message_id(cls, value: str) -> str:
        return validate_provider_message_id(value)


class DispatchDisposition(StrEnum):
    CONFIRMED = "confirmed"
    FAILED_BEFORE_EFFECT = "failed_before_effect"
    OUTCOME_UNKNOWN = "outcome_unknown"


class ProviderDispatchResult(ContractModel):
    provider: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,49}$")
    disposition: DispatchDisposition
    receipt: ProviderReceipt | None = None
    provider_reference: str | None = Field(default=None, max_length=500)
    detail: str = Field(min_length=2, max_length=1000)

    @field_validator("provider_reference")
    @classmethod
    def validate_reference(cls, value: str | None) -> str | None:
        return None if value is None else validate_provider_message_id(value)

    @model_validator(mode="after")
    def require_receipt_for_confirmation(self) -> Self:
        if self.disposition is DispatchDisposition.CONFIRMED and self.receipt is None:
            raise ValueError("confirmed provider result requires a receipt")
        if self.disposition is not DispatchDisposition.CONFIRMED and self.receipt is not None:
            raise ValueError("non-confirmed provider result cannot include a receipt")
        if self.receipt is not None and self.receipt.provider != self.provider:
            raise ValueError("provider result and receipt must name the same provider")
        return self


class ReconciliationDisposition(StrEnum):
    CONFIRMED = "confirmed"
    SAFE_TO_RETRY = "safe_to_retry"
    NEEDS_OPERATOR = "needs_operator"


class ProviderReconciliationResult(ContractModel):
    provider: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,49}$")
    disposition: ReconciliationDisposition
    receipt: ProviderReceipt | None = None
    provider_reference: str | None = Field(default=None, max_length=500)
    detail: str = Field(min_length=2, max_length=1000)

    @field_validator("provider_reference")
    @classmethod
    def validate_reference(cls, value: str | None) -> str | None:
        return None if value is None else validate_provider_message_id(value)

    @model_validator(mode="after")
    def require_receipt_for_confirmation(self) -> Self:
        if self.disposition is ReconciliationDisposition.CONFIRMED and self.receipt is None:
            raise ValueError("confirmed reconciliation requires a receipt")
        if self.disposition is not ReconciliationDisposition.CONFIRMED and self.receipt is not None:
            raise ValueError("non-confirmed reconciliation cannot include a receipt")
        if self.receipt is not None and self.receipt.provider != self.provider:
            raise ValueError("provider result and receipt must name the same provider")
        return self


class ProviderAuditEvent(ContractModel):
    """Secret-free state transition suitable for durable audit storage."""

    action_intent_id: UUID
    state: ActionOutcomeState
    occurred_at: datetime = Field(default_factory=utc_now)
    provider: str | None = Field(default=None, max_length=50)
    provider_reference: str | None = Field(default=None, max_length=500)
    detail: str = Field(min_length=2, max_length=1000)


class EmailExecutionRecord(ContractModel):
    """Current execution state plus its deterministic audit trail."""

    action_intent_id: UUID
    state: ActionOutcomeState
    payload_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    provider_request_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    idempotency_key_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    attempts: int = Field(default=0, ge=0)
    provider_reference: str | None = Field(default=None, max_length=500)
    receipt: ProviderReceipt | None = None
    detail: str = Field(min_length=2, max_length=1000)
    updated_at: datetime = Field(default_factory=utc_now)
    audit_events: tuple[ProviderAuditEvent, ...] = ()

    @classmethod
    def approved(
        cls,
        request: EmailDispatchRequest,
        *,
        at: datetime,
    ) -> EmailExecutionRecord:
        provider_request = json.dumps(
            request.message.model_dump(mode="json"),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        return cls(
            action_intent_id=request.action_intent_id,
            state=ActionOutcomeState.APPROVED,
            payload_fingerprint=request.payload_fingerprint,
            provider_request_fingerprint=sha256(provider_request).hexdigest(),
            idempotency_key_sha256=sha256(request.idempotency_key.encode()).hexdigest(),
            detail="Authorized action is ready for email dispatch",
            updated_at=at,
            audit_events=(
                ProviderAuditEvent(
                    action_intent_id=request.action_intent_id,
                    state=ActionOutcomeState.APPROVED,
                    occurred_at=at,
                    detail="Authorized action entered the email execution boundary",
                ),
            ),
        )
