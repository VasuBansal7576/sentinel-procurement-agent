"""Immutable evidence snapshots, exact provenance, freshness, and conflicts."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from typing import Protocol, Self
from uuid import UUID

from pydantic import Field, model_validator

from sentinel_api.domain import (
    Artifact,
    ArtifactKind,
    ContractModel,
    EvidenceClassification,
    EvidenceConflict,
    EvidenceObservation,
    EvidenceSource,
)
from sentinel_api.domain.common import ScalarValue
from sentinel_api.research.models import TaintLabel, UntrustedContent


class EvidenceSnapshot(ContractModel):
    """Immutable response bytes plus their domain artifact reference."""

    artifact: Artifact
    content: UntrustedContent

    @model_validator(mode="after")
    def verify_artifact_binding(self) -> Self:
        if self.artifact.kind is not ArtifactKind.EVIDENCE_SNAPSHOT:
            raise ValueError("snapshot artifact has the wrong kind")
        if self.artifact.sha256 != self.content.content_sha256:
            raise ValueError("snapshot artifact digest does not match content")
        if self.artifact.size_bytes != len(self.content.body):
            raise ValueError("snapshot artifact size does not match content")
        if self.artifact.media_type != self.content.media_type:
            raise ValueError("snapshot artifact media type does not match content")
        return self


class SnapshotStore(Protocol):
    async def put(
        self,
        *,
        run_id: UUID,
        request_revision_id: UUID,
        producer: str,
        content: UntrustedContent,
    ) -> EvidenceSnapshot:
        """Persist immutable response bytes and return an artifact-bound snapshot."""

    async def get(self, artifact_id: UUID) -> EvidenceSnapshot:
        """Load an immutable evidence snapshot."""


class InMemorySnapshotStore:
    """Content-addressed reference storage with immutable artifact records."""

    def __init__(self) -> None:
        self._blobs: dict[str, bytes] = {}
        self._snapshots: dict[UUID, EvidenceSnapshot] = {}

    async def put(
        self,
        *,
        run_id: UUID,
        request_revision_id: UUID,
        producer: str,
        content: UntrustedContent,
    ) -> EvidenceSnapshot:
        existing_blob = self._blobs.get(content.content_sha256)
        if existing_blob is not None and existing_blob != content.body:
            raise ValueError("content digest collision detected")
        self._blobs[content.content_sha256] = content.body
        artifact = Artifact(
            kind=ArtifactKind.EVIDENCE_SNAPSHOT,
            object_key=f"evidence/sha256/{content.content_sha256}",
            media_type=content.media_type,
            size_bytes=len(content.body),
            sha256=content.content_sha256,
            run_id=run_id,
            request_revision_id=request_revision_id,
            producer=producer,
            immutable=True,
        )
        snapshot = EvidenceSnapshot(artifact=artifact, content=content)
        self._snapshots[artifact.id] = snapshot
        return snapshot

    async def get(self, artifact_id: UUID) -> EvidenceSnapshot:
        try:
            return self._snapshots[artifact_id]
        except KeyError as error:
            raise KeyError("evidence snapshot not found") from error


class ExactSpan(ContractModel):
    """Byte-independent character offsets and digest for an exact source quote."""

    start: int = Field(ge=0)
    end: int = Field(gt=0)
    text: str = Field(min_length=1, max_length=4000)
    text_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    content_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def validate_offsets_and_hash(self) -> Self:
        if self.end <= self.start:
            raise ValueError("exact span end must be after start")
        if self.end - self.start != len(self.text):
            raise ValueError("exact span offsets do not match text length")
        if sha256(self.text.encode()).hexdigest() != self.text_sha256:
            raise ValueError("exact span digest does not match text")
        return self


class ClaimProvenance(ContractModel):
    source: EvidenceSource
    span: ExactSpan

    @model_validator(mode="after")
    def require_matching_content(self) -> ClaimProvenance:
        if self.source.content_sha256 != self.span.content_sha256:
            raise ValueError("source and exact span refer to different content")
        if self.source.exact_span != self.span.text:
            raise ValueError("domain source and exact span text differ")
        return self


class VerifiedObservation(ContractModel):
    observation: EvidenceObservation
    provenance: ClaimProvenance
    taint: frozenset[TaintLabel] = Field(min_length=1)

    @model_validator(mode="after")
    def verify_source_and_taint(self) -> VerifiedObservation:
        if self.observation.source != self.provenance.source:
            raise ValueError("observation source does not match provenance")
        if TaintLabel.REMOTE_CONTENT not in self.taint:
            raise ValueError("remote observation must retain source taint")
        return self


def locate_exact_span(snapshot: EvidenceSnapshot, text: str, *, occurrence: int = 0) -> ExactSpan:
    """Locate a quote deterministically and bind it to response and quote hashes."""

    if not text:
        raise ValueError("exact span text cannot be empty")
    if occurrence < 0:
        raise ValueError("exact span occurrence cannot be negative")
    decoded = snapshot.content.body.decode("utf-8", errors="strict")
    start = -1
    search_from = 0
    for _ in range(occurrence + 1):
        start = decoded.find(text, search_from)
        if start < 0:
            raise ValueError("exact span does not occur in snapshot content")
        search_from = start + len(text)
    return ExactSpan(
        start=start,
        end=start + len(text),
        text=text,
        text_sha256=sha256(text.encode()).hexdigest(),
        content_sha256=snapshot.content.content_sha256,
    )


def build_verified_observation(
    *,
    snapshot: EvidenceSnapshot,
    request_revision_id: UUID,
    candidate_id: UUID | None,
    requirement_key: str,
    value: ScalarValue,
    exact_text: str,
    extractor_version: str,
    confidence: float,
    evidence_type: str | None = None,
    normalized_unit: str | None = None,
    fresh_until: datetime | None = None,
    occurrence: int = 0,
) -> VerifiedObservation:
    """Create a domain observation only after exact source verification."""

    if snapshot.artifact.request_revision_id != request_revision_id:
        raise ValueError("snapshot belongs to a different request revision")
    span = locate_exact_span(snapshot, exact_text, occurrence=occurrence)
    source = EvidenceSource(
        url=snapshot.content.url,
        retrieved_at=snapshot.content.retrieved_at,
        content_sha256=snapshot.content.content_sha256,
        media_type=snapshot.content.media_type,
        response_artifact_id=snapshot.artifact.id,
        exact_span=span.text,
    )
    observation = EvidenceObservation(
        request_revision_id=request_revision_id,
        candidate_id=candidate_id,
        requirement_key=requirement_key,
        evidence_type=evidence_type,
        value=value,
        normalized_unit=normalized_unit,
        classification=EvidenceClassification.OBSERVED,
        source=source,
        extractor_version=extractor_version,
        confidence=confidence,
        fresh_until=fresh_until,
    )
    return VerifiedObservation(
        observation=observation,
        provenance=ClaimProvenance(source=source, span=span),
        taint=snapshot.content.taint,
    )


class FreshnessState(StrEnum):
    CURRENT = "current"
    STALE = "stale"
    UNBOUNDED = "unbounded"


def freshness_at(observation: EvidenceObservation, at: datetime) -> FreshnessState:
    if observation.fresh_until is None:
        return FreshnessState.UNBOUNDED
    if observation.fresh_until.tzinfo is None or at.tzinfo is None:
        raise ValueError("freshness comparison requires timezone-aware timestamps")
    if at <= observation.fresh_until:
        return FreshnessState.CURRENT
    return FreshnessState.STALE


class ConflictGroup(ContractModel):
    conflict: EvidenceConflict
    observations: tuple[EvidenceObservation, ...] = Field(min_length=2)

    @model_validator(mode="after")
    def verify_membership(self) -> ConflictGroup:
        expected_ids = tuple(observation.id for observation in self.observations)
        if self.conflict.observation_ids != expected_ids:
            raise ValueError("conflict IDs do not match grouped observations")
        return self

    def resolve(self, observation_id: UUID) -> ConflictGroup:
        if observation_id not in self.conflict.observation_ids:
            raise ValueError("conflict can only be resolved by a grouped observation")
        return self.model_copy(
            update={
                "conflict": self.conflict.model_copy(
                    update={"resolved_by_observation_id": observation_id}
                )
            }
        )


def find_conflicts(
    observations: tuple[EvidenceObservation, ...],
) -> tuple[ConflictGroup, ...]:
    """Find differing claims at the same revision, candidate, and requirement grain."""

    grouped: dict[tuple[UUID, UUID | None, str], list[EvidenceObservation]] = {}
    for observation in observations:
        if observation.classification is EvidenceClassification.UNKNOWN:
            continue
        key = (
            observation.request_revision_id,
            observation.candidate_id,
            observation.requirement_key,
        )
        grouped.setdefault(key, []).append(observation)

    conflicts: list[ConflictGroup] = []
    for (_revision_id, _candidate_id, requirement_key), members in grouped.items():
        values = {_comparable_value(member.value) for member in members}
        if len(members) >= 2 and len(values) >= 2:
            conflict = EvidenceConflict(
                requirement_key=requirement_key,
                observation_ids=tuple(member.id for member in members),
                summary=f"{len(values)} differing values observed for {requirement_key}",
            )
            conflicts.append(ConflictGroup(conflict=conflict, observations=tuple(members)))
    return tuple(conflicts)


def _comparable_value(value: ScalarValue) -> tuple[str, str]:
    return (type(value).__name__, str(value))
