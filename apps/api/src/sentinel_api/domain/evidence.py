"""Claim-level evidence, provenance, and conflict contracts."""

from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import Field, HttpUrl

from sentinel_api.domain.common import ContractModel, ScalarValue, utc_now


class EvidenceClassification(StrEnum):
    OPERATOR_PROVIDED = "operator_provided"
    OBSERVED = "observed"
    CALCULATED = "calculated"
    INFERRED = "inferred"
    CONFLICTING = "conflicting"
    UNKNOWN = "unknown"


class EvidenceSource(ContractModel):
    url: HttpUrl
    retrieved_at: datetime = Field(default_factory=utc_now)
    content_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    media_type: str = Field(min_length=3, max_length=160)
    response_artifact_id: UUID | None = None
    screenshot_artifact_id: UUID | None = None
    exact_span: str | None = Field(default=None, max_length=4000)


class EvidenceObservation(ContractModel):
    id: UUID = Field(default_factory=uuid4)
    request_revision_id: UUID
    candidate_id: UUID | None = None
    requirement_key: str = Field(pattern=r"^[a-z][a-z0-9_.-]{1,79}$")
    value: ScalarValue
    normalized_unit: str | None = Field(default=None, max_length=64)
    classification: EvidenceClassification
    source: EvidenceSource | None = None
    extractor_version: str = Field(min_length=1, max_length=80)
    schema_version: int = Field(default=1, ge=1)
    confidence: float = Field(ge=0, le=1)
    fresh_until: datetime | None = None
    derived_from: tuple[UUID, ...] = ()


class EvidenceConflict(ContractModel):
    id: UUID = Field(default_factory=uuid4)
    requirement_key: str = Field(pattern=r"^[a-z][a-z0-9_.-]{1,79}$")
    observation_ids: tuple[UUID, ...] = Field(min_length=2)
    summary: str = Field(min_length=2, max_length=1000)
    resolved_by_observation_id: UUID | None = None
