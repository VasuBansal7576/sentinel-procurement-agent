"""Evidence resolution, hard constraints, weighted scoring, and ranking."""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from uuid import UUID

from sentinel_api.domain.common import ScalarValue
from sentinel_api.domain.evidence import (
    EvidenceClassification,
    EvidenceConflict,
    EvidenceObservation,
)
from sentinel_api.domain.procurement import (
    Candidate,
    CriterionOperator,
    CriterionType,
    Requirement,
    RequirementPriority,
)
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
    UnitNormalizer,
    normalize_currency_code,
)


@dataclass(frozen=True)
class _ResolvedEvidence:
    status: EvaluationStatus
    value: ScalarValue
    normalized_unit: str | None
    observation_ids: tuple[UUID, ...]
    selected_observation_id: UUID | None
    reason: str


_USABLE_CLASSIFICATIONS = {
    EvidenceClassification.OPERATOR_PROVIDED,
    EvidenceClassification.OBSERVED,
    EvidenceClassification.CALCULATED,
    EvidenceClassification.INFERRED,
}

_CLASSIFICATION_PRIORITY = {
    EvidenceClassification.OPERATOR_PROVIDED: 4,
    EvidenceClassification.OBSERVED: 3,
    EvidenceClassification.CALCULATED: 2,
    EvidenceClassification.INFERRED: 1,
}


def _as_decimal(value: ScalarValue) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (Decimal, int)):
        raise NormalizationError("numeric evidence must be an integer or Decimal")
    try:
        return Decimal(value)
    except InvalidOperation as error:
        raise NormalizationError("numeric evidence is invalid") from error


def _normalize_value(
    requirement: Requirement,
    observation: EvidenceObservation,
    *,
    unit_normalizer: UnitNormalizer,
    currency_table: CurrencyTable | None,
) -> tuple[ScalarValue, str | None]:
    criterion = requirement.criterion
    value = observation.value

    if criterion.type is CriterionType.NUMBER:
        if observation.normalized_unit is None or criterion.unit is None:
            raise NormalizationError("number evidence requires both source and target units")
        return (
            unit_normalizer.convert(
                _as_decimal(value),
                observation.normalized_unit,
                criterion.unit,
            ),
            unit_normalizer.canonical_unit(criterion.unit),
        )

    if criterion.type is CriterionType.MONEY:
        if observation.normalized_unit is None or criterion.currency is None:
            raise NormalizationError("money evidence requires both source and target currencies")
        amount = _as_decimal(value)
        source_currency = normalize_currency_code(observation.normalized_unit)
        target_currency = normalize_currency_code(criterion.currency)
        if source_currency == target_currency:
            return amount, target_currency
        if currency_table is None:
            raise NormalizationError(
                f"currency conversion from {source_currency} to {target_currency} "
                "requires an explicit rate table"
            )
        return currency_table.convert(amount, source_currency, target_currency), target_currency

    if criterion.type is CriterionType.BOOLEAN:
        if not isinstance(value, bool):
            raise NormalizationError("boolean evidence must be a boolean")
        return value, None

    if criterion.type is CriterionType.DATE:
        if not isinstance(value, datetime):
            raise NormalizationError("date evidence must be a datetime")
        return value, None

    if criterion.type in {
        CriterionType.ENUM,
        CriterionType.GEOGRAPHY,
        CriterionType.CERTIFICATION,
        CriterionType.TEXT,
    }:
        if not isinstance(value, str):
            raise NormalizationError(f"{criterion.type.value} evidence must be text")
        return value.strip(), None

    return value, observation.normalized_unit


def _value_key(value: ScalarValue) -> tuple[str, str]:
    if isinstance(value, bool):
        return "bool", str(value)
    if isinstance(value, Decimal):
        return "decimal", str(value.normalize())
    if isinstance(value, int):
        return "decimal", str(Decimal(value).normalize())
    if isinstance(value, datetime):
        return "datetime", value.isoformat()
    if isinstance(value, str):
        return "text", value.casefold()
    return "none", ""


def _select_observation(observations: Iterable[EvidenceObservation]) -> EvidenceObservation:
    return max(
        observations,
        key=lambda observation: (
            observation.confidence,
            _CLASSIFICATION_PRIORITY.get(observation.classification, 0),
            observation.source.retrieved_at.isoformat() if observation.source else "",
            str(observation.id),
        ),
    )


def _related_resolution(
    observations: Sequence[EvidenceObservation],
    conflicts: Sequence[EvidenceConflict],
    requirement_key: str,
) -> tuple[bool, UUID | None]:
    observation_ids = {observation.id for observation in observations}
    resolved_ids: set[UUID] = set()
    for conflict in conflicts:
        if conflict.requirement_key != requirement_key:
            continue
        if not observation_ids.intersection(conflict.observation_ids):
            continue
        if conflict.resolved_by_observation_id is None:
            return True, None
        if conflict.resolved_by_observation_id not in conflict.observation_ids:
            return True, None
        resolved_ids.add(conflict.resolved_by_observation_id)
    if len(resolved_ids) > 1:
        return True, None
    return False, next(iter(resolved_ids), None)


def _resolve_evidence(
    candidate: Candidate,
    requirement: Requirement,
    observations: Sequence[EvidenceObservation],
    conflicts: Sequence[EvidenceConflict],
    *,
    as_of: datetime,
    unit_normalizer: UnitNormalizer,
    currency_table: CurrencyTable | None,
) -> _ResolvedEvidence:
    relevant = tuple(
        observation
        for observation in observations
        if observation.request_revision_id == candidate.request_revision_id
        and observation.candidate_id == candidate.id
        and observation.requirement_key == requirement.key
    )
    observation_ids = tuple(sorted((observation.id for observation in relevant), key=str))
    if not relevant:
        return _ResolvedEvidence(
            status=EvaluationStatus.UNKNOWN,
            value=None,
            normalized_unit=None,
            observation_ids=(),
            selected_observation_id=None,
            reason="no evidence observation was provided",
        )

    has_unresolved_conflict, conflict_resolution = _related_resolution(
        relevant,
        conflicts,
        requirement.key,
    )
    if has_unresolved_conflict:
        return _ResolvedEvidence(
            status=EvaluationStatus.CONFLICTING,
            value=None,
            normalized_unit=None,
            observation_ids=observation_ids,
            selected_observation_id=None,
            reason="evidence has an unresolved or inconsistent conflict",
        )

    selected_by_resolution: EvidenceObservation | None = None
    if conflict_resolution is not None:
        selected_by_resolution = next(
            (observation for observation in relevant if observation.id == conflict_resolution),
            None,
        )
        if selected_by_resolution is None:
            return _ResolvedEvidence(
                status=EvaluationStatus.INVALID,
                value=None,
                normalized_unit=None,
                observation_ids=observation_ids,
                selected_observation_id=None,
                reason="conflict resolution references unavailable evidence",
            )

    if selected_by_resolution is None and any(
        observation.classification is EvidenceClassification.CONFLICTING for observation in relevant
    ):
        return _ResolvedEvidence(
            status=EvaluationStatus.CONFLICTING,
            value=None,
            normalized_unit=None,
            observation_ids=observation_ids,
            selected_observation_id=None,
            reason="an observation explicitly marks the evidence as conflicting",
        )

    considered = (selected_by_resolution,) if selected_by_resolution else relevant
    fresh = tuple(
        observation
        for observation in considered
        if observation.fresh_until is None or observation.fresh_until >= as_of
    )
    usable = tuple(
        observation
        for observation in fresh
        if observation.classification in _USABLE_CLASSIFICATIONS
    )
    if not usable:
        if fresh != considered:
            return _ResolvedEvidence(
                status=EvaluationStatus.STALE,
                value=None,
                normalized_unit=None,
                observation_ids=observation_ids,
                selected_observation_id=None,
                reason="all usable evidence is stale",
            )
        return _ResolvedEvidence(
            status=EvaluationStatus.UNKNOWN,
            value=None,
            normalized_unit=None,
            observation_ids=observation_ids,
            selected_observation_id=None,
            reason="evidence is explicitly unknown",
        )

    normalized: list[tuple[EvidenceObservation, ScalarValue, str | None]] = []
    errors: list[str] = []
    for observation in usable:
        try:
            value, unit = _normalize_value(
                requirement,
                observation,
                unit_normalizer=unit_normalizer,
                currency_table=currency_table,
            )
        except NormalizationError as error:
            errors.append(str(error))
        else:
            normalized.append((observation, value, unit))
    if not normalized:
        return _ResolvedEvidence(
            status=EvaluationStatus.INVALID,
            value=None,
            normalized_unit=None,
            observation_ids=observation_ids,
            selected_observation_id=None,
            reason="; ".join(sorted(set(errors))),
        )

    distinct_values = {_value_key(value) for _, value, _ in normalized}
    if len(distinct_values) > 1:
        return _ResolvedEvidence(
            status=EvaluationStatus.CONFLICTING,
            value=None,
            normalized_unit=None,
            observation_ids=observation_ids,
            selected_observation_id=None,
            reason="usable observations disagree after normalization",
        )

    selected = _select_observation(observation for observation, _, _ in normalized)
    selected_value, selected_unit = next(
        (value, unit) for observation, value, unit in normalized if observation.id == selected.id
    )
    return _ResolvedEvidence(
        status=EvaluationStatus.SATISFIED,
        value=selected_value,
        normalized_unit=selected_unit,
        observation_ids=observation_ids,
        selected_observation_id=selected.id,
        reason="evidence resolved deterministically",
    )


def _comparable_text(value: ScalarValue) -> str:
    if not isinstance(value, str):
        raise NormalizationError("text comparison requires text values")
    return value.strip().casefold()


def _compare_decimal(
    operator: CriterionOperator,
    observed: Decimal,
    target: Decimal,
) -> bool:
    if operator is CriterionOperator.EQUALS:
        return observed == target
    if operator is CriterionOperator.NOT_EQUALS:
        return observed != target
    if operator is CriterionOperator.AT_LEAST:
        return observed >= target
    if operator is CriterionOperator.AT_MOST:
        return observed <= target
    raise NormalizationError(f"operator {operator.value!r} is invalid for numeric criteria")


def _compare_datetime(
    operator: CriterionOperator,
    observed: datetime,
    target: datetime,
) -> bool:
    if (
        observed.tzinfo is None
        or observed.utcoffset() is None
        or target.tzinfo is None
        or target.utcoffset() is None
    ):
        raise NormalizationError("date comparison requires timezone-aware values")
    if operator is CriterionOperator.EQUALS:
        return observed == target
    if operator is CriterionOperator.NOT_EQUALS:
        return observed != target
    if operator is CriterionOperator.AT_LEAST:
        return observed >= target
    if operator is CriterionOperator.AT_MOST:
        return observed <= target
    raise NormalizationError(f"operator {operator.value!r} is invalid for date criteria")


def _compare_equality(
    operator: CriterionOperator,
    observed: ScalarValue,
    target: ScalarValue,
) -> bool:
    if operator is CriterionOperator.EQUALS:
        return observed == target
    if operator is CriterionOperator.NOT_EQUALS:
        return observed != target
    raise NormalizationError(f"operator {operator.value!r} supports neither ordering nor text")


def _criterion_satisfied(requirement: Requirement, value: ScalarValue) -> bool:
    criterion = requirement.criterion
    operator = criterion.operator
    target = criterion.target

    if operator is CriterionOperator.EXISTS:
        return value is not None
    if operator is CriterionOperator.CONTAINS:
        return _comparable_text(target) in _comparable_text(value)
    if operator is CriterionOperator.IN:
        if not criterion.allowed_values:
            raise NormalizationError("'in' criteria require allowed_values")
        return _comparable_text(value) in {
            allowed_value.strip().casefold() for allowed_value in criterion.allowed_values
        }

    if criterion.type in {CriterionType.NUMBER, CriterionType.MONEY}:
        return _compare_decimal(operator, _as_decimal(value), _as_decimal(target))
    if criterion.type is CriterionType.DATE:
        if not isinstance(value, datetime) or not isinstance(target, datetime):
            raise NormalizationError("date comparison requires datetime values")
        return _compare_datetime(operator, value, target)
    if criterion.type is CriterionType.BOOLEAN:
        if not isinstance(value, bool) or not isinstance(target, bool):
            raise NormalizationError("boolean comparison requires boolean values")
        return _compare_equality(operator, value, target)
    if criterion.type in {
        CriterionType.ENUM,
        CriterionType.GEOGRAPHY,
        CriterionType.CERTIFICATION,
        CriterionType.TEXT,
    }:
        observed_text = _comparable_text(value)
        target_text = _comparable_text(target)
        return _compare_equality(operator, observed_text, target_text)
    return _compare_equality(operator, value, target)


def evaluate_requirement(
    candidate: Candidate,
    requirement: Requirement,
    observations: Sequence[EvidenceObservation],
    conflicts: Sequence[EvidenceConflict] = (),
    *,
    as_of: datetime,
    unit_normalizer: UnitNormalizer | None = None,
    currency_table: CurrencyTable | None = None,
) -> RequirementEvaluation:
    """Resolve evidence and apply one requirement without model or network calls."""

    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    resolved = _resolve_evidence(
        candidate,
        requirement,
        observations,
        conflicts,
        as_of=as_of,
        unit_normalizer=unit_normalizer or UnitNormalizer(),
        currency_table=currency_table,
    )
    possible_weight = (
        requirement.criterion.weight
        if requirement.priority is RequirementPriority.PREFERRED
        else Decimal("0")
    )
    if resolved.status is not EvaluationStatus.SATISFIED:
        return RequirementEvaluation(
            requirement=requirement,
            status=resolved.status,
            value=resolved.value,
            normalized_unit=resolved.normalized_unit,
            observation_ids=resolved.observation_ids,
            selected_observation_id=resolved.selected_observation_id,
            reason=resolved.reason,
            earned_weight=Decimal("0"),
            possible_weight=possible_weight,
        )
    try:
        satisfied = _criterion_satisfied(requirement, resolved.value)
    except NormalizationError as error:
        return RequirementEvaluation(
            requirement=requirement,
            status=EvaluationStatus.INVALID,
            value=resolved.value,
            normalized_unit=resolved.normalized_unit,
            observation_ids=resolved.observation_ids,
            selected_observation_id=resolved.selected_observation_id,
            reason=str(error),
            earned_weight=Decimal("0"),
            possible_weight=possible_weight,
        )
    status = EvaluationStatus.SATISFIED if satisfied else EvaluationStatus.NOT_SATISFIED
    return RequirementEvaluation(
        requirement=requirement,
        status=status,
        value=resolved.value,
        normalized_unit=resolved.normalized_unit,
        observation_ids=resolved.observation_ids,
        selected_observation_id=resolved.selected_observation_id,
        reason="criterion satisfied" if satisfied else "criterion not satisfied",
        earned_weight=possible_weight if satisfied else Decimal("0"),
        possible_weight=possible_weight,
    )


def _coverage(evaluations: Sequence[RequirementEvaluation]) -> EvidenceCoverage:
    total = len(evaluations)
    supported = sum(evaluation.evidence_supported for evaluation in evaluations)
    unknown = sum(evaluation.status is EvaluationStatus.UNKNOWN for evaluation in evaluations)
    conflicting = sum(
        evaluation.status is EvaluationStatus.CONFLICTING for evaluation in evaluations
    )
    stale = sum(evaluation.status is EvaluationStatus.STALE for evaluation in evaluations)
    invalid = sum(evaluation.status is EvaluationStatus.INVALID for evaluation in evaluations)
    mandatory = tuple(
        evaluation
        for evaluation in evaluations
        if evaluation.requirement.priority is RequirementPriority.MANDATORY
    )
    mandatory_supported = sum(evaluation.evidence_supported for evaluation in mandatory)
    return EvidenceCoverage(
        total=total,
        supported=supported,
        unknown=unknown,
        conflicting=conflicting,
        stale=stale,
        invalid=invalid,
        percent=Decimal("100") if total == 0 else Decimal(supported) * 100 / Decimal(total),
        mandatory_total=len(mandatory),
        mandatory_supported=mandatory_supported,
        mandatory_percent=(
            Decimal("100")
            if not mandatory
            else Decimal(mandatory_supported) * 100 / Decimal(len(mandatory))
        ),
    )


def evaluate_candidate(
    candidate: Candidate,
    requirements: Sequence[Requirement],
    observations: Sequence[EvidenceObservation],
    conflicts: Sequence[EvidenceConflict] = (),
    *,
    as_of: datetime,
    unit_normalizer: UnitNormalizer | None = None,
    currency_table: CurrencyTable | None = None,
) -> CandidateEvaluation:
    """Evaluate all requirements, mandatory eligibility, coverage, and preferred score."""

    requirement_keys = [requirement.key for requirement in requirements]
    if len(requirement_keys) != len(set(requirement_keys)):
        raise ValueError("requirement keys must be unique for candidate evaluation")
    normalizer = unit_normalizer or UnitNormalizer()
    evaluations = tuple(
        evaluate_requirement(
            candidate,
            requirement,
            observations,
            conflicts,
            as_of=as_of,
            unit_normalizer=normalizer,
            currency_table=currency_table,
        )
        for requirement in requirements
    )
    mandatory = tuple(
        evaluation
        for evaluation in evaluations
        if evaluation.requirement.priority is RequirementPriority.MANDATORY
    )
    failed = tuple(
        evaluation.requirement.key
        for evaluation in mandatory
        if evaluation.status is EvaluationStatus.NOT_SATISFIED
    )
    unresolved = tuple(
        evaluation.requirement.key for evaluation in mandatory if not evaluation.evidence_supported
    )
    possible_weight = sum(
        (evaluation.possible_weight for evaluation in evaluations),
        start=Decimal("0"),
    )
    earned_weight = sum(
        (evaluation.earned_weight for evaluation in evaluations),
        start=Decimal("0"),
    )
    score = (
        Decimal("0") if possible_weight == 0 else earned_weight * Decimal("100") / possible_weight
    )
    return CandidateEvaluation(
        candidate=candidate,
        requirements=evaluations,
        eligible=not failed and not unresolved,
        score=score,
        coverage=_coverage(evaluations),
        failed_mandatory_keys=failed,
        unresolved_mandatory_keys=unresolved,
    )


def rank_candidates(evaluations: Sequence[CandidateEvaluation]) -> RankingResult:
    """Rank candidates with deterministic tie-breakers and no implicit recommendation."""

    candidate_ids = [evaluation.candidate.id for evaluation in evaluations]
    if len(candidate_ids) != len(set(candidate_ids)):
        raise ValueError("candidate IDs must be unique for ranking")
    ordered = sorted(
        evaluations,
        key=lambda evaluation: (
            not evaluation.eligible,
            -evaluation.score,
            -evaluation.coverage.mandatory_percent,
            -evaluation.coverage.percent,
            evaluation.candidate.supplier.legal_name.casefold(),
            evaluation.candidate.offering_name.casefold(),
            str(evaluation.candidate.id),
        ),
    )
    ranked = tuple(
        RankedCandidate(rank=index, evaluation=evaluation)
        for index, evaluation in enumerate(ordered, start=1)
    )
    recommended = (
        ranked[0].evaluation.candidate.id if ranked and ranked[0].evaluation.eligible else None
    )
    return RankingResult(candidates=ranked, recommended_candidate_id=recommended)
