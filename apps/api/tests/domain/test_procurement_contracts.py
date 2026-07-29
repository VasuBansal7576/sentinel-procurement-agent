from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from sentinel_api.domain import (
    CategoryField,
    CategorySchema,
    Criterion,
    CriterionOperator,
    CriterionType,
    LineItem,
    Lot,
    Money,
    Quantity,
    RequestRevision,
    Requirement,
    RequirementPriority,
)


def category_schema() -> CategorySchema:
    return CategorySchema(
        name="General hardware",
        fields=(
            CategoryField(
                key="weight",
                label="Weight",
                type=CriterionType.NUMBER,
                unit="kg",
                required=True,
                description="Shipping weight",
            ),
        ),
    )


def lot() -> Lot:
    return Lot(
        name="Primary lot",
        line_items=(
            LineItem(
                name="Equipment",
                description="Category-generic equipment",
                quantity=Quantity(value=Decimal("10"), unit="each"),
                category_schema=category_schema(),
            ),
        ),
    )


def test_money_normalizes_currency() -> None:
    assert Money(amount=Decimal("14.25"), currency="usd").currency == "USD"


def test_money_criterion_requires_currency() -> None:
    with pytest.raises(ValidationError, match="money criteria require currency"):
        Criterion(
            type=CriterionType.MONEY,
            operator=CriterionOperator.AT_MOST,
            target=Decimal("100"),
        )


def test_request_revision_requires_lineage_after_first_revision() -> None:
    with pytest.raises(ValidationError, match="later revisions require"):
        RequestRevision(
            case_id=uuid4(),
            revision_number=2,
            reason="Changed delivery requirement",
            lots=(lot(),),
        )


def test_contracts_reject_unknown_fields() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        Money(amount=Decimal("10"), currency="USD", invented=True)  # type: ignore[call-arg]


def test_requirement_keys_are_unique_across_the_request_revision() -> None:
    shared_requirement = Requirement(
        key="delivery",
        label="Delivery requirement",
        description="Delivery within the requested window",
        subject_path="delivery.days",
        priority=RequirementPriority.MANDATORY,
        criterion=Criterion(
            type=CriterionType.NUMBER,
            operator=CriterionOperator.AT_MOST,
            target=10,
            unit="day",
        ),
    )
    first = lot()
    second = Lot(
        name="Secondary lot",
        line_items=(
            first.line_items[0].model_copy(
                update={
                    "id": uuid4(),
                    "requirements": (shared_requirement,),
                }
            ),
        ),
    )
    first_with_requirement = first.model_copy(
        update={
            "line_items": (
                first.line_items[0].model_copy(update={"requirements": (shared_requirement,)}),
            )
        }
    )

    with pytest.raises(ValidationError, match="unique across"):
        RequestRevision(
            case_id=uuid4(),
            revision_number=1,
            reason="Initial request",
            lots=(first_with_requirement, second),
        )
