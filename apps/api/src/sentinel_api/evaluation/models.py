"""Immutable results emitted by the deterministic evaluation engine."""

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from sentinel_api.domain.common import ScalarValue
from sentinel_api.domain.procurement import Candidate, Requirement


class EvaluationStatus(StrEnum):
    SATISFIED = "satisfied"
    NOT_SATISFIED = "not_satisfied"
    UNKNOWN = "unknown"
    CONFLICTING = "conflicting"
    STALE = "stale"
    INVALID = "invalid"


@dataclass(frozen=True)
class RequirementEvaluation:
    requirement: Requirement
    status: EvaluationStatus
    value: ScalarValue
    normalized_unit: str | None
    observation_ids: tuple[UUID, ...]
    selected_observation_id: UUID | None
    reason: str
    earned_weight: Decimal
    possible_weight: Decimal

    @property
    def evidence_supported(self) -> bool:
        return self.status in {
            EvaluationStatus.SATISFIED,
            EvaluationStatus.NOT_SATISFIED,
        }


@dataclass(frozen=True)
class EvidenceCoverage:
    total: int
    supported: int
    unknown: int
    conflicting: int
    stale: int
    invalid: int
    percent: Decimal
    mandatory_total: int
    mandatory_supported: int
    mandatory_percent: Decimal


@dataclass(frozen=True)
class CandidateEvaluation:
    candidate: Candidate
    requirements: tuple[RequirementEvaluation, ...]
    eligible: bool
    score: Decimal
    coverage: EvidenceCoverage
    failed_mandatory_keys: tuple[str, ...]
    unresolved_mandatory_keys: tuple[str, ...]


@dataclass(frozen=True)
class RankedCandidate:
    rank: int
    evaluation: CandidateEvaluation


@dataclass(frozen=True)
class RankingResult:
    candidates: tuple[RankedCandidate, ...]
    recommended_candidate_id: UUID | None
