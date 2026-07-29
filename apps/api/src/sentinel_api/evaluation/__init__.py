"""Deterministic candidate evaluation, normalization, and ranking."""

from sentinel_api.evaluation.engine import evaluate_candidate, evaluate_requirement, rank_candidates
from sentinel_api.evaluation.models import (
    CandidateEvaluation,
    EvaluationStatus,
    EvidenceCoverage,
    RankedCandidate,
    RankingResult,
    RequirementEvaluation,
)
from sentinel_api.evaluation.normalization import (
    CurrencyTable,
    NormalizationError,
    UnitDefinition,
    UnitNormalizer,
    normalize_currency_code,
)

__all__ = [
    "CandidateEvaluation",
    "CurrencyTable",
    "EvaluationStatus",
    "EvidenceCoverage",
    "NormalizationError",
    "RankedCandidate",
    "RankingResult",
    "RequirementEvaluation",
    "UnitDefinition",
    "UnitNormalizer",
    "evaluate_candidate",
    "evaluate_requirement",
    "normalize_currency_code",
    "rank_candidates",
]
