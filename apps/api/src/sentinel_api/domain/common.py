"""Shared primitives for immutable domain contracts."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

type ScalarValue = str | int | Decimal | bool | datetime | None
type EntityId = UUID


def utc_now() -> datetime:
    """Return an aware UTC timestamp."""

    return datetime.now(UTC)


class ContractModel(BaseModel):
    """Strict immutable base for data crossing a domain boundary."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
        validate_default=True,
    )
