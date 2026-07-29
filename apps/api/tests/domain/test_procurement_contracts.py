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
