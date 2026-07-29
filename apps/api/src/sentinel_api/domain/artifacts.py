"""Versioned evidence and deliverable artifact contracts."""

from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import Field

from sentinel_api.domain.common import ContractModel, utc_now


class ArtifactKind(StrEnum):
    EVIDENCE_SNAPSHOT = "evidence_snapshot"
    SCREENSHOT = "screenshot"
    REQUIREMENTS_SPECIFICATION = "requirements_specification"
    COMPARISON_WORKBOOK = "comparison_workbook"
    RECOMMENDATION_REPORT = "recommendation_report"
    RFQ_PACKAGE = "rfq_package"
    ACTION_RECEIPT = "action_receipt"
    AUDIT_SUMMARY = "audit_summary"


class Artifact(ContractModel):
    id: UUID = Field(default_factory=uuid4)
    version: int = Field(default=1, ge=1)
    kind: ArtifactKind
    object_key: str = Field(min_length=3, max_length=1024)
    media_type: str = Field(min_length=3, max_length=160)
    size_bytes: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    run_id: UUID
    request_revision_id: UUID
    producer: str = Field(min_length=2, max_length=160)
    approval_version: int | None = Field(default=None, ge=1)
    immutable: bool = False
    created_at: datetime = Field(default_factory=utc_now)
