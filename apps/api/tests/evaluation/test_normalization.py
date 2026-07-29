from decimal import Decimal

import pytest

from sentinel_api.evaluation import (
    CurrencyTable,
    NormalizationError,
    UnitDefinition,
    UnitNormalizer,
)


def test_unit_normalization_converts_aliases_and_affine_units() -> None:
    normalizer = UnitNormalizer()

    assert normalizer.convert(Decimal("2500"), "grams", "kg") == Decimal("2.500")
    assert normalizer.convert(Decimal("32"), "fahrenheit", "celsius") == Decimal("0")
    assert normalizer.convert(Decimal("1"), "tb", "gb") == Decimal("1000")


def test_identical_category_specific_units_do_not_require_a_registry_entry() -> None:
    normalizer = UnitNormalizer()

    assert normalizer.convert(Decimal("14"), "seat/month", "seat/month") == Decimal("14")


def test_unit_normalizer_supports_explicit_category_extensions() -> None:
    normalizer = UnitNormalizer(
        definitions={
            "case": UnitDefinition("packaging_count", Decimal("12")),
            "carton": UnitDefinition("packaging_count", Decimal("24")),
        },
        aliases={"cases": "case"},
    )

    assert normalizer.convert(Decimal("2"), "cases", "carton") == Decimal("1")


def test_unit_normalization_fails_closed_for_unknown_or_incompatible_units() -> None:
    normalizer = UnitNormalizer()

    with pytest.raises(NormalizationError, match="cannot convert"):
        normalizer.convert(Decimal("1"), "widgets", "kg")
    with pytest.raises(NormalizationError, match="incompatible"):
        normalizer.convert(Decimal("1"), "kg", "m")


def test_currency_conversion_uses_only_explicit_rates() -> None:
    rates = CurrencyTable(
        base_currency="usd",
        rates_to_base={"EUR": Decimal("1.10"), "INR": Decimal("0.0125")},
    )

    assert rates.base_currency == "USD"
    assert rates.convert(Decimal("90"), "EUR", "USD") == Decimal("99.00")
    assert rates.convert(Decimal("88"), "USD", "EUR") == Decimal("8E+1")
    assert rates.convert(Decimal("8000"), "INR", "EUR") == Decimal("90.90909090909090909090909091")


def test_currency_conversion_requires_available_positive_rates() -> None:
    rates = CurrencyTable(base_currency="USD", rates_to_base={"EUR": Decimal("1.1")})

    with pytest.raises(NormalizationError, match="missing currency rate for GBP"):
        rates.convert(Decimal("10"), "GBP", "USD")
    with pytest.raises(ValueError, match="must be positive"):
        CurrencyTable(base_currency="USD", rates_to_base={"EUR": Decimal("0")})
    with pytest.raises(ValueError, match="exactly 1"):
        CurrencyTable(base_currency="USD", rates_to_base={"USD": Decimal("1.01")})


def test_currency_table_copies_rates_to_prevent_ambient_mutation() -> None:
    source = {"EUR": Decimal("1.1")}
    rates = CurrencyTable(base_currency="USD", rates_to_base=source)

    source["EUR"] = Decimal("2")

    assert rates.convert(Decimal("10"), "EUR", "USD") == Decimal("11.0")
