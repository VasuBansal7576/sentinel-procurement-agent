"""Closed, deterministic unit and caller-supplied currency normalization."""

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType


class NormalizationError(ValueError):
    """Raised when a value cannot be normalized without guessing."""


def _decimal(value: Decimal | int) -> Decimal:
    if isinstance(value, bool):
        raise NormalizationError("boolean values are not numeric measurements")
    if isinstance(value, Decimal):
        return value
    return Decimal(value)


def normalize_currency_code(value: str) -> str:
    """Return an uppercase ISO-style code or fail instead of guessing."""

    code = value.strip().upper()
    if len(code) != 3 or not code.isalpha():
        raise NormalizationError(f"invalid currency code: {value!r}")
    return code


@dataclass(frozen=True)
class UnitDefinition:
    """Affine conversion from one unit to a dimension's base unit."""

    dimension: str
    factor_to_base: Decimal
    offset_to_base: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        if not self.dimension.strip():
            raise ValueError("unit dimension cannot be empty")
        if self.factor_to_base <= 0:
            raise ValueError("unit factor must be positive")


_DEFAULT_DEFINITIONS: dict[str, UnitDefinition] = {
    "each": UnitDefinition("count", Decimal("1")),
    "kg": UnitDefinition("mass", Decimal("1")),
    "g": UnitDefinition("mass", Decimal("0.001")),
    "mg": UnitDefinition("mass", Decimal("0.000001")),
    "lb": UnitDefinition("mass", Decimal("0.45359237")),
    "oz": UnitDefinition("mass", Decimal("0.028349523125")),
    "m": UnitDefinition("length", Decimal("1")),
    "cm": UnitDefinition("length", Decimal("0.01")),
    "mm": UnitDefinition("length", Decimal("0.001")),
    "km": UnitDefinition("length", Decimal("1000")),
    "in": UnitDefinition("length", Decimal("0.0254")),
    "ft": UnitDefinition("length", Decimal("0.3048")),
    "l": UnitDefinition("volume", Decimal("1")),
    "ml": UnitDefinition("volume", Decimal("0.001")),
    "m3": UnitDefinition("volume", Decimal("1000")),
    "s": UnitDefinition("duration", Decimal("1")),
    "min": UnitDefinition("duration", Decimal("60")),
    "h": UnitDefinition("duration", Decimal("3600")),
    "day": UnitDefinition("duration", Decimal("86400")),
    "w": UnitDefinition("power", Decimal("1")),
    "kw": UnitDefinition("power", Decimal("1000")),
    "pa": UnitDefinition("pressure", Decimal("1")),
    "kpa": UnitDefinition("pressure", Decimal("1000")),
    "bar": UnitDefinition("pressure", Decimal("100000")),
    "byte": UnitDefinition("digital_storage", Decimal("1")),
    "kb": UnitDefinition("digital_storage", Decimal("1000")),
    "mb": UnitDefinition("digital_storage", Decimal("1000000")),
    "gb": UnitDefinition("digital_storage", Decimal("1000000000")),
    "tb": UnitDefinition("digital_storage", Decimal("1000000000000")),
    "c": UnitDefinition("temperature", Decimal("1")),
    "f": UnitDefinition(
        "temperature",
        Decimal(5) / Decimal(9),
        -(Decimal(160) / Decimal(9)),
    ),
    "k": UnitDefinition("temperature", Decimal("1"), Decimal("-273.15")),
}

_DEFAULT_ALIASES: dict[str, str] = {
    "unit": "each",
    "units": "each",
    "item": "each",
    "items": "each",
    "ea": "each",
    "kilogram": "kg",
    "kilograms": "kg",
    "gram": "g",
    "grams": "g",
    "milligram": "mg",
    "milligrams": "mg",
    "pound": "lb",
    "pounds": "lb",
    "ounce": "oz",
    "ounces": "oz",
    "meter": "m",
    "meters": "m",
    "metre": "m",
    "metres": "m",
    "centimeter": "cm",
    "centimeters": "cm",
    "millimeter": "mm",
    "millimeters": "mm",
    "kilometer": "km",
    "kilometers": "km",
    "inch": "in",
    "inches": "in",
    "foot": "ft",
    "feet": "ft",
    "liter": "l",
    "liters": "l",
    "litre": "l",
    "litres": "l",
    "milliliter": "ml",
    "milliliters": "ml",
    "second": "s",
    "seconds": "s",
    "minute": "min",
    "minutes": "min",
    "hour": "h",
    "hours": "h",
    "days": "day",
    "watt": "w",
    "watts": "w",
    "kilowatt": "kw",
    "kilowatts": "kw",
    "°c": "c",
    "celsius": "c",
    "°f": "f",
    "fahrenheit": "f",
    "kelvin": "k",
}


class UnitNormalizer:
    """Normalize known units, with explicit extensions for category-specific units."""

    def __init__(
        self,
        definitions: Mapping[str, UnitDefinition] | None = None,
        aliases: Mapping[str, str] | None = None,
    ) -> None:
        merged_definitions = dict(_DEFAULT_DEFINITIONS)
        if definitions is not None:
            merged_definitions.update(
                {self._raw_symbol(symbol): definition for symbol, definition in definitions.items()}
            )
        merged_aliases = dict(_DEFAULT_ALIASES)
        if aliases is not None:
            merged_aliases.update(
                {
                    self._raw_symbol(alias): self._raw_symbol(symbol)
                    for alias, symbol in aliases.items()
                }
            )
        unknown_aliases = set(merged_aliases.values()) - set(merged_definitions)
        if unknown_aliases:
            unknown = ", ".join(sorted(unknown_aliases))
            raise ValueError(f"unit aliases reference undefined units: {unknown}")
        self._definitions = MappingProxyType(merged_definitions)
        self._aliases = MappingProxyType(merged_aliases)

    @staticmethod
    def _raw_symbol(unit: str) -> str:
        symbol = unit.strip().casefold()
        if not symbol:
            raise NormalizationError("unit cannot be empty")
        return symbol

    def canonical_unit(self, unit: str) -> str:
        symbol = self._raw_symbol(unit)
        return self._aliases.get(symbol, symbol)

    def convert(
        self,
        value: Decimal | int,
        source_unit: str,
        target_unit: str,
    ) -> Decimal:
        amount = _decimal(value)
        source = self.canonical_unit(source_unit)
        target = self.canonical_unit(target_unit)
        if source == target:
            return amount

        source_definition = self._definitions.get(source)
        target_definition = self._definitions.get(target)
        if source_definition is None or target_definition is None:
            raise NormalizationError(f"cannot convert {source_unit!r} to {target_unit!r}")
        if source_definition.dimension != target_definition.dimension:
            raise NormalizationError(
                f"incompatible unit dimensions: {source_unit!r} and {target_unit!r}"
            )

        base_value = amount * source_definition.factor_to_base + source_definition.offset_to_base
        return (base_value - target_definition.offset_to_base) / target_definition.factor_to_base


@dataclass(frozen=True)
class CurrencyTable:
    """Explicit currency rates expressed as units of base currency per currency."""

    base_currency: str
    rates_to_base: Mapping[str, Decimal]

    def __post_init__(self) -> None:
        base = normalize_currency_code(self.base_currency)
        normalized: dict[str, Decimal] = {}
        for currency, rate in self.rates_to_base.items():
            code = normalize_currency_code(currency)
            decimal_rate = _decimal(rate)
            if decimal_rate <= 0:
                raise ValueError(f"currency rate for {code} must be positive")
            normalized[code] = decimal_rate
        existing_base_rate = normalized.get(base)
        if existing_base_rate is not None and existing_base_rate != Decimal("1"):
            raise ValueError("the base currency rate must be exactly 1")
        normalized[base] = Decimal("1")
        object.__setattr__(self, "base_currency", base)
        object.__setattr__(self, "rates_to_base", MappingProxyType(normalized))

    def convert(
        self,
        amount: Decimal | int,
        source_currency: str,
        target_currency: str,
    ) -> Decimal:
        value = _decimal(amount)
        source = normalize_currency_code(source_currency)
        target = normalize_currency_code(target_currency)
        if source == target:
            return value
        try:
            source_rate = self.rates_to_base[source]
            target_rate = self.rates_to_base[target]
        except KeyError as error:
            raise NormalizationError(f"missing currency rate for {error.args[0]}") from error
        return value * source_rate / target_rate
