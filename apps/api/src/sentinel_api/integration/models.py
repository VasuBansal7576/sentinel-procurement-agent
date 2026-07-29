"""Application-owned records and HTTP projections for generic integration."""

from datetime import datetime
from hashlib import sha256
from typing import Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from sentinel_api.domain import ContractModel, utc_now


class IntegrationRecord(ContractModel):
    """A compact run-scoped record; large bytes never enter journal events."""

    run_id: UUID
    record_ref: UUID
    record_kind: str = Field(min_length=2, max_length=80)
    payload: dict[str, object] = Field(default_factory=dict)
    content: bytes | None = None
    filename: str | None = None
    media_type: str | None = None
    content_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    version: int = Field(default=1, ge=1)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_content_binding(self) -> Self:
        metadata = (self.filename, self.media_type, self.content_sha256)
        if self.content is None:
            if any(value is not None for value in metadata):
                raise ValueError("content metadata requires artifact bytes")
            return self
        if any(value is None for value in metadata):
            raise ValueError("artifact bytes require filename, media type, and digest")
        assert self.content_sha256 is not None
        if sha256(self.content).hexdigest() != self.content_sha256:
            raise ValueError("artifact content digest does not match bytes")
        return self


class CommandRequest(ContractModel):
    command_id: UUID
    reason: str = Field(min_length=2, max_length=1000)


class MessageCommandRequest(ContractModel):
    command_id: UUID
    message_id: UUID
    text: str = Field(min_length=1, max_length=4000)


class RedirectCommandRequest(ContractModel):
    command_id: UUID
    text: str = Field(min_length=2, max_length=4000)
    changed_dependencies: tuple[str, ...] = Field(min_length=1)


class ProposalEditRequest(ContractModel):
    recipient: str = Field(min_length=3, max_length=320)
    subject: str = Field(min_length=1, max_length=998)
    body: str = Field(min_length=1, max_length=100_000)


class ProposalDecisionRequest(ContractModel):
    decision: Literal["approve", "reject"]
    approver_id: UUID


class RetryRequest(ContractModel):
    command_id: UUID


class CommandAckView(ContractModel):
    command_id: UUID
    accepted: bool
    sequence: int
    detail: str


class ArtifactDownload(ContractModel):
    run_id: UUID
    artifact_id: UUID
    filename: str
    media_type: str
    content_sha256: str
    content: bytes
