from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest

from sentinel_api.domain import (
    Candidate,
    Criterion,
    CriterionOperator,
    CriterionType,
    EvidenceClassification,
    EvidenceConflict,
    EvidenceObservation,
    Requirement,
    RequirementPriority,
    Supplier,
)
from sentinel_api.evaluation import (
    CurrencyTable,
    EvaluationStatus,
    evaluate_candidate,
    evaluate_requirement,
    rank_candidates,
)

AS_OF = datetime(2026, 7, 29, 12, tzinfo=UTC)
REVISION_ID = UUID(int=1)
LOT_ID = UUID(int=2)


def candidate(number: int, supplier_name: str = "Supplier") -> Candidate:
    return Candidate(
        id=UUID(int=number),
        request_revision_id=REVISION_ID,
        lot_id=LOT_ID,
        supplier=Supplier(id=UUID(int=100 + number), legal_name=supplier_name),
        offering_name=f"Offering {number}",
        source_url=f"https://supplier{number}.example/item",
    )


def requirement(
    key: str,
    *,
    criterion_type: CriterionType,
    operator: CriterionOperator,
    target: str | int | Decimal | bool | datetime | None,
    priority: RequirementPriority = RequirementPriority.MANDATORY,
    unit: str | None = None,
    currency: str | None = None,
    allowed_values: tuple[str, ...] = (),
    weight: Decimal = Decimal("1"),
) -> Requirement:
    return Requirement(
        id=UUID(int=1000 + len(key)),
        key=key,
        label=f"{key} requirement",
        description=f"Criterion for {key}",
        subject_path=f"attributes.{key}",
        priority=priority,
        criterion=Criterion(
            type=criterion_type,
            operator=operator,
            target=target,
            unit=unit,
            currency=currency,
            allowed_values=allowed_values,
            weight=weight,
        ),
    )


def observation(
    number: int,
    owner: Candidate,
    requirement_key: str,
    value: str | int | Decimal | bool | datetime | None,
    *,
    unit: str | None = None,
    classification: EvidenceClassification = EvidenceClassification.OBSERVED,
    fresh_until: datetime | None = None,
    confidence: float = 0.9,
    evidence_type: str | None = None,
) -> EvidenceObservation:
    return EvidenceObservation(
        id=UUID(int=10_000 + number),
        request_revision_id=owner.request_revision_id,
        candidate_id=owner.id,
        requirement_key=requirement_key,
        evidence_type=evidence_type,
        value=value,
        normalized_unit=unit,
        classification=classification,
        extractor_version="test-1",
        confidence=confidence,
        fresh_until=fresh_until,
    )


def test_hard_constraints_weighted_score_currency_units_and_coverage() -> None:
    item = candidate(10)
    weight = requirement(
        "shipping_weight",
        criterion_type=CriterionType.NUMBER,
        operator=CriterionOperator.AT_MOST,
        target=Decimal("1"),
        unit="kg",
    )
    price = requirement(
        "price",
        criterion_type=CriterionType.MONEY,
        operator=CriterionOperator.AT_MOST,
        target=Decimal("100"),
        currency="USD",
        priority=RequirementPriority.PREFERRED,
        weight=Decimal("3"),
    )
    warranty = requirement(
        "warranty",
        criterion_type=CriterionType.BOOLEAN,
        operator=CriterionOperator.EQUALS,
        target=True,
        priority=RequirementPriority.PREFERRED,
        weight=Decimal("1"),
    )
    observations = (
        observation(1, item, "shipping_weight", Decimal("500"), unit="g"),
        observation(2, item, "price", Decimal("90"), unit="EUR"),
        observation(
            3,
            item,
            "warranty",
            None,
            classification=EvidenceClassification.UNKNOWN,
        ),
    )

    result = evaluate_candidate(
        item,
        (weight, price, warranty),
        observations,
        as_of=AS_OF,
        currency_table=CurrencyTable(
            base_currency="USD",
            rates_to_base={"EUR": Decimal("1.1")},
        ),
    )

    assert result.eligible
    assert result.score == Decimal("75")
    assert result.coverage.supported == 2
    assert result.coverage.unknown == 1
    assert result.coverage.percent == Decimal(200) / Decimal(3)
    assert result.coverage.mandatory_percent == Decimal("100")
    assert result.requirements[0].value == Decimal("0.500")
    assert result.requirements[1].value == Decimal("99.0")
    assert result.requirements[2].status is EvaluationStatus.UNKNOWN


def test_failed_and_unresolved_mandatory_constraints_are_both_ineligible() -> None:
    item = candidate(11)
    budget = requirement(
        "budget",
        criterion_type=CriterionType.MONEY,
        operator=CriterionOperator.AT_MOST,
        target=Decimal("100"),
        currency="USD",
    )
    delivery = requirement(
        "delivery",
        criterion_type=CriterionType.NUMBER,
        operator=CriterionOperator.AT_MOST,
        target=Decimal("5"),
        unit="day",
    )

    result = evaluate_candidate(
        item,
        (budget, delivery),
        (
            observation(4, item, "budget", Decimal("120"), unit="USD"),
            observation(
                5,
                item,
                "delivery",
                None,
                classification=EvidenceClassification.UNKNOWN,
            ),
        ),
        as_of=AS_OF,
    )

    assert not result.eligible
    assert result.failed_mandatory_keys == ("budget",)
    assert result.unresolved_mandatory_keys == ("delivery",)


def test_unresolved_conflict_and_explicit_conflicting_evidence_remain_conflicting() -> None:
    item = candidate(12)
    certification = requirement(
        "certification",
        criterion_type=CriterionType.CERTIFICATION,
        operator=CriterionOperator.EQUALS,
        target="ISO 9001",
    )
    first = observation(6, item, "certification", "ISO 9001")
    second = observation(7, item, "certification", "None")

    unresolved = evaluate_requirement(
        item,
        certification,
        (first, second),
        (
            EvidenceConflict(
                requirement_key="certification",
                observation_ids=(first.id, second.id),
                summary="Supplier page and registry disagree",
            ),
        ),
        as_of=AS_OF,
    )
    explicit = evaluate_requirement(
        item,
        certification,
        (
            observation(
                8,
                item,
                "certification",
                None,
                classification=EvidenceClassification.CONFLICTING,
            ),
        ),
        as_of=AS_OF,
    )

    assert unresolved.status is EvaluationStatus.CONFLICTING
    assert explicit.status is EvaluationStatus.CONFLICTING


def test_resolved_conflict_selects_the_designated_observation() -> None:
    item = candidate(13)
    certification = requirement(
        "certification",
        criterion_type=CriterionType.CERTIFICATION,
        operator=CriterionOperator.EQUALS,
        target="ISO 9001",
    )
    first = observation(9, item, "certification", "ISO 9001", confidence=0.6)
    second = observation(10, item, "certification", "None", confidence=0.99)

    result = evaluate_requirement(
        item,
        certification,
        (first, second),
        (
            EvidenceConflict(
                requirement_key="certification",
                observation_ids=(first.id, second.id),
                summary="Registry resolves supplier ambiguity",
                resolved_by_observation_id=first.id,
            ),
        ),
        as_of=AS_OF,
    )

    assert result.status is EvaluationStatus.SATISFIED
    assert result.selected_observation_id == first.id
    assert result.value == "ISO 9001"


def test_disagreement_is_detected_after_normalization_but_equivalent_values_coalesce() -> None:
    item = candidate(14)
    weight = requirement(
        "weight",
        criterion_type=CriterionType.NUMBER,
        operator=CriterionOperator.AT_MOST,
        target=Decimal("2"),
        unit="kg",
    )
    kilograms = observation(11, item, "weight", Decimal("1"), unit="kg")
    equivalent_grams = observation(12, item, "weight", Decimal("1000"), unit="g")
    different_grams = observation(13, item, "weight", Decimal("900"), unit="g")

    equivalent = evaluate_requirement(
        item,
        weight,
        (kilograms, equivalent_grams),
        as_of=AS_OF,
    )
    disagreement = evaluate_requirement(
        item,
        weight,
        (kilograms, different_grams),
        as_of=AS_OF,
    )

    assert equivalent.status is EvaluationStatus.SATISFIED
    assert equivalent.value == Decimal("1")
    assert (
        evaluate_requirement(
            item,
            weight,
            (equivalent_grams, kilograms),
            as_of=AS_OF,
        )
        == equivalent
    )
    assert disagreement.status is EvaluationStatus.CONFLICTING


def test_stale_and_unconvertible_evidence_fail_closed() -> None:
    item = candidate(15)
    duration = requirement(
        "duration",
        criterion_type=CriterionType.NUMBER,
        operator=CriterionOperator.AT_MOST,
        target=Decimal("3"),
        unit="day",
    )

    stale = evaluate_requirement(
        item,
        duration,
        (
            observation(
                14,
                item,
                "duration",
                Decimal("2"),
                unit="day",
                fresh_until=AS_OF - timedelta(seconds=1),
            ),
        ),
        as_of=AS_OF,
    )
    invalid = evaluate_requirement(
        item,
        duration,
        (observation(15, item, "duration", Decimal("2"), unit="parsec"),),
        as_of=AS_OF,
    )

    assert stale.status is EvaluationStatus.STALE
    assert invalid.status is EvaluationStatus.INVALID
    assert "cannot convert" in invalid.reason


def test_invalid_currency_codes_and_naive_dates_fail_closed() -> None:
    item = candidate(150)
    malformed_money = requirement(
        "malformed_money",
        criterion_type=CriterionType.MONEY,
        operator=CriterionOperator.AT_MOST,
        target=Decimal("10"),
        currency="$$$",
    )
    naive_date = requirement(
        "naive_date",
        criterion_type=CriterionType.DATE,
        operator=CriterionOperator.AT_LEAST,
        target=datetime(2026, 8, 1),
    )

    money_result = evaluate_requirement(
        item,
        malformed_money,
        (observation(150, item, "malformed_money", Decimal("5"), unit="$$$"),),
        as_of=AS_OF,
    )
    date_result = evaluate_requirement(
        item,
        naive_date,
        (observation(151, item, "naive_date", datetime(2026, 8, 2)),),
        as_of=AS_OF,
    )

    assert money_result.status is EvaluationStatus.INVALID
    assert "invalid currency code" in money_result.reason
    assert date_result.status is EvaluationStatus.INVALID
    assert "timezone-aware" in date_result.reason


def test_conflicts_for_a_different_requirement_do_not_contaminate_evidence() -> None:
    item = candidate(151)
    required = requirement(
        "available",
        criterion_type=CriterionType.BOOLEAN,
        operator=CriterionOperator.EQUALS,
        target=True,
    )
    observed = observation(152, item, "available", True)

    result = evaluate_requirement(
        item,
        required,
        (observed,),
        (
            EvidenceConflict(
                requirement_key="different_key",
                observation_ids=(observed.id, UUID(int=99_999)),
                summary="Unrelated evidence conflict",
            ),
        ),
        as_of=AS_OF,
    )

    assert result.status is EvaluationStatus.SATISFIED


@pytest.mark.parametrize(
    ("criterion_type", "operator", "target", "value", "allowed_values", "expected"),
    [
        (CriterionType.BOOLEAN, CriterionOperator.EQUALS, True, True, (), True),
        (CriterionType.TEXT, CriterionOperator.NOT_EQUALS, "red", "blue", (), True),
        (CriterionType.TEXT, CriterionOperator.CONTAINS, "support", "24/7 Support", (), True),
        (
            CriterionType.GEOGRAPHY,
            CriterionOperator.IN,
            "unused",
            "IN",
            ("IN", "US"),
            True,
        ),
        (CriterionType.CERTIFICATION, CriterionOperator.EXISTS, None, "SOC 2", (), True),
        (
            CriterionType.DATE,
            CriterionOperator.AT_LEAST,
            datetime(2026, 8, 1, tzinfo=UTC),
            datetime(2026, 8, 2, tzinfo=UTC),
            (),
            True,
        ),
    ],
)
def test_criterion_operators_are_applied_deterministically(
    criterion_type: CriterionType,
    operator: CriterionOperator,
    target: str | bool | datetime | None,
    value: str | bool | datetime,
    allowed_values: tuple[str, ...],
    expected: bool,
) -> None:
    item = candidate(16)
    criterion = requirement(
        "generic",
        criterion_type=criterion_type,
        operator=operator,
        target=target,
        allowed_values=allowed_values,
    )

    result = evaluate_requirement(
        item,
        criterion,
        (observation(16, item, "generic", value),),
        as_of=AS_OF,
    )

    assert (result.status is EvaluationStatus.SATISFIED) is expected


def test_ranking_prioritizes_eligibility_then_score_and_stable_names() -> None:
    mandatory = requirement(
        "mandatory",
        criterion_type=CriterionType.BOOLEAN,
        operator=CriterionOperator.EQUALS,
        target=True,
    )
    preferred = requirement(
        "preferred",
        criterion_type=CriterionType.BOOLEAN,
        operator=CriterionOperator.EQUALS,
        target=True,
        priority=RequirementPriority.PREFERRED,
    )
    alpha = candidate(21, "Alpha")
    beta = candidate(22, "Beta")
    ineligible = candidate(23, "Aardvark")
    alpha_result = evaluate_candidate(
        alpha,
        (mandatory, preferred),
        (
            observation(21, alpha, "mandatory", True),
            observation(22, alpha, "preferred", True),
        ),
        as_of=AS_OF,
    )
    beta_result = evaluate_candidate(
        beta,
        (mandatory, preferred),
        (
            observation(23, beta, "mandatory", True),
            observation(24, beta, "preferred", True),
        ),
        as_of=AS_OF,
    )
    ineligible_result = evaluate_candidate(
        ineligible,
        (mandatory, preferred),
        (
            observation(25, ineligible, "mandatory", False),
            observation(26, ineligible, "preferred", True),
        ),
        as_of=AS_OF,
    )

    ranking = rank_candidates((ineligible_result, beta_result, alpha_result))

    assert [ranked.evaluation.candidate.id for ranked in ranking.candidates] == [
        alpha.id,
        beta.id,
        ineligible.id,
    ]
    assert ranking.recommended_candidate_id == alpha.id


def test_ambiguous_requirement_keys_and_duplicate_rank_entries_are_rejected() -> None:
    item = candidate(24)
    required = requirement(
        "available",
        criterion_type=CriterionType.BOOLEAN,
        operator=CriterionOperator.EQUALS,
        target=True,
    )

    with pytest.raises(ValueError, match="requirement keys must be unique"):
        evaluate_candidate(
            item,
            (required, required),
            (observation(27, item, "available", True),),
            as_of=AS_OF,
        )

    evaluation = evaluate_candidate(
        item,
        (required,),
        (observation(28, item, "available", True),),
        as_of=AS_OF,
    )
    with pytest.raises(ValueError, match="candidate IDs must be unique"):
        rank_candidates((evaluation, evaluation))


def test_acceptable_evidence_type_is_enforced() -> None:
    item = candidate(25)
    required = Requirement(
        id=UUID(int=2025),
        key="certification",
        label="Certification requirement",
        description="Must be supported by a certification registry",
        subject_path="attributes.certification",
        priority=RequirementPriority.MANDATORY,
        acceptable_evidence=("certification_registry",),
        criterion=Criterion(
            type=CriterionType.CERTIFICATION,
            operator=CriterionOperator.EQUALS,
            target="ISO 9001",
        ),
    )

    rejected = evaluate_requirement(
        item,
        required,
        (
            observation(
                29,
                item,
                "certification",
                "ISO 9001",
                evidence_type="supplier_page",
            ),
        ),
        as_of=AS_OF,
    )
    accepted = evaluate_requirement(
        item,
        required,
        (
            observation(
                30,
                item,
                "certification",
                "ISO 9001",
                evidence_type="certification_registry",
            ),
        ),
        as_of=AS_OF,
    )

    assert rejected.status is EvaluationStatus.INVALID
    assert accepted.status is EvaluationStatus.SATISFIED


@pytest.mark.parametrize(
    ("category", "criterion_type", "operator", "target", "value", "unit"),
    [
        (
            "office hardware",
            CriterionType.NUMBER,
            CriterionOperator.AT_MOST,
            Decimal("2000"),
            Decimal("1500"),
            "g",
        ),
        (
            "industrial component",
            CriterionType.CERTIFICATION,
            CriterionOperator.EQUALS,
            "ISO 9001",
            "ISO 9001",
            None,
        ),
        (
            "packaging",
            CriterionType.NUMBER,
            CriterionOperator.AT_LEAST,
            Decimal("0.5"),
            Decimal("0.7"),
            "mm",
        ),
        (
            "SaaS",
            CriterionType.BOOLEAN,
            CriterionOperator.EQUALS,
            True,
            True,
            None,
        ),
        (
            "local service",
            CriterionType.GEOGRAPHY,
            CriterionOperator.EQUALS,
            "Pune",
            "pune",
            None,
        ),
    ],
)
def test_evaluation_is_category_generic(
    category: str,
    criterion_type: CriterionType,
    operator: CriterionOperator,
    target: str | Decimal | bool,
    value: str | Decimal | bool,
    unit: str | None,
) -> None:
    item = candidate(30)
    category_requirement = requirement(
        "category_check",
        criterion_type=criterion_type,
        operator=operator,
        target=target,
        unit=unit if criterion_type is CriterionType.NUMBER else None,
    )

    result = evaluate_requirement(
        item,
        category_requirement,
        (observation(30, item, "category_check", value, unit=unit),),
        as_of=AS_OF,
    )

    assert result.status is EvaluationStatus.SATISFIED, category


def test_as_of_must_be_explicitly_timezone_aware() -> None:
    item = candidate(31)
    required = requirement(
        "available",
        criterion_type=CriterionType.BOOLEAN,
        operator=CriterionOperator.EQUALS,
        target=True,
    )

    with pytest.raises(ValueError, match="timezone-aware"):
        evaluate_requirement(
            item,
            required,
            (observation(31, item, "available", True),),
            as_of=datetime(2026, 7, 29),
        )
