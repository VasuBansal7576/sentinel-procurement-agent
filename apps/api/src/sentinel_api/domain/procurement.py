"""Category-generic procurement request and candidate contracts."""

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Self
from uuid import UUID, uuid4

from pydantic import Field, field_validator, model_validator

from sentinel_api.domain.common import ContractModel, ScalarValue, utc_now
from sentinel_api.domain.policy import RequestPolicyOverlay


class ProcurementCaseStatus(StrEnum):
    DRAFT = "draft"
    READY = "ready"
    RUNNING = "running"
    PAUSED = "paused"
    AWAITING_APPROVAL = "awaiting_approval"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class CriterionType(StrEnum):
    BOOLEAN = "boolean"
    ENUM = "enum"
    NUMBER = "number"
    MONEY = "money"
    DATE = "date"
    GEOGRAPHY = "geography"
    CERTIFICATION = "certification"
    TEXT = "text"
    EVIDENCE_ASSERTION = "evidence_assertion"


class CriterionOperator(StrEnum):
    EQUALS = "equals"
    NOT_EQUALS = "not_equals"
    AT_LEAST = "at_least"
    AT_MOST = "at_most"
    IN = "in"
    CONTAINS = "contains"
    EXISTS = "exists"


class RequirementPriority(StrEnum):
    MANDATORY = "mandatory"
    PREFERRED = "preferred"
    INFORMATIONAL = "informational"


class Money(ContractModel):
    amount: Decimal = Field(ge=0, max_digits=18, decimal_places=4)
    currency: str = Field(min_length=3, max_length=3)

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        if not value.isalpha():
            raise ValueError("currency must be a three-letter ISO-style code")
        return value.upper()


class Quantity(ContractModel):
    value: Decimal = Field(gt=0, max_digits=18, decimal_places=6)
    unit: str = Field(min_length=1, max_length=64)


class Criterion(ContractModel):
    type: CriterionType
    operator: CriterionOperator
    target: ScalarValue = None
    unit: str | None = Field(default=None, max_length=64)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    allowed_values: tuple[str, ...] = ()
    weight: Decimal = Field(default=Decimal("1"), ge=0, le=100)

    @model_validator(mode="after")
    def validate_type_specific_fields(self) -> Self:
        if self.operator is not CriterionOperator.EXISTS and self.target is None:
            raise ValueError("target is required unless the operator is 'exists'")
        if self.type is CriterionType.ENUM and not self.allowed_values:
            raise ValueError("enum criteria require allowed_values")
        if self.type is CriterionType.MONEY and not self.currency:
            raise ValueError("money criteria require currency")
        if self.type is CriterionType.NUMBER and not self.unit:
            raise ValueError("number criteria require a unit")
        return self


class Requirement(ContractModel):
    id: UUID = Field(default_factory=uuid4)
    key: str = Field(pattern=r"^[a-z][a-z0-9_.-]{1,79}$")
    label: str = Field(min_length=2, max_length=160)
    description: str = Field(min_length=2, max_length=1000)
    subject_path: str = Field(min_length=1, max_length=240)
    priority: RequirementPriority
    criterion: Criterion
    acceptable_evidence: tuple[str, ...] = ()


class CategoryField(ContractModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_.-]{1,79}$")
    label: str = Field(min_length=2, max_length=160)
    type: CriterionType
    unit: str | None = Field(default=None, max_length=64)
    required: bool = False
    description: str = Field(min_length=2, max_length=1000)


class CategorySchema(ContractModel):
    id: UUID = Field(default_factory=uuid4)
    name: str = Field(min_length=2, max_length=160)
    classification_code: str | None = Field(default=None, max_length=64)
    version: int = Field(default=1, ge=1)
    fields: tuple[CategoryField, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def ensure_unique_field_keys(self) -> Self:
        keys = [field.key for field in self.fields]
        if len(keys) != len(set(keys)):
            raise ValueError("category field keys must be unique")
        return self


class LineItem(ContractModel):
    id: UUID = Field(default_factory=uuid4)
    name: str = Field(min_length=2, max_length=200)
    description: str = Field(min_length=2, max_length=2000)
    quantity: Quantity
    category_schema: CategorySchema
    requirements: tuple[Requirement, ...] = ()

    @model_validator(mode="after")
    def ensure_unique_requirement_keys(self) -> Self:
        keys = [requirement.key for requirement in self.requirements]
        if len(keys) != len(set(keys)):
            raise ValueError("requirement keys must be unique within a line item")
        return self


class Lot(ContractModel):
    id: UUID = Field(default_factory=uuid4)
    name: str = Field(min_length=2, max_length=160)
    line_items: tuple[LineItem, ...] = Field(min_length=1)


class RequestRevision(ContractModel):
    id: UUID = Field(default_factory=uuid4)
    case_id: UUID
    revision_number: int = Field(ge=1)
    previous_revision_id: UUID | None = None
    reason: str = Field(min_length=2, max_length=500)
    lots: tuple[Lot, ...] = Field(min_length=1)
    policy_overlay: RequestPolicyOverlay = Field(default_factory=RequestPolicyOverlay)
    created_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_revision_lineage_and_lots(self) -> Self:
        if self.revision_number == 1 and self.previous_revision_id is not None:
            raise ValueError("the first revision cannot have a previous revision")
        if self.revision_number > 1 and self.previous_revision_id is None:
            raise ValueError("later revisions require previous_revision_id")
        lot_ids = [lot.id for lot in self.lots]
        if len(lot_ids) != len(set(lot_ids)):
            raise ValueError("lot IDs must be unique")
        requirement_keys = [
            requirement.key
            for lot in self.lots
            for line_item in lot.line_items
            for requirement in line_item.requirements
        ]
        if len(requirement_keys) != len(set(requirement_keys)):
            raise ValueError("requirement keys must be unique across a request revision")
        return self


class ProcurementCase(ContractModel):
    id: UUID = Field(default_factory=uuid4)
    organization_id: UUID
    title: str = Field(min_length=2, max_length=200)
    status: ProcurementCaseStatus = ProcurementCaseStatus.DRAFT
    current_revision_id: UUID | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class Supplier(ContractModel):
    id: UUID = Field(default_factory=uuid4)
    legal_name: str = Field(min_length=2, max_length=240)
    website: str | None = Field(default=None, max_length=2048)
    country_code: str | None = Field(default=None, min_length=2, max_length=2)
    identifiers: tuple[str, ...] = ()


class Candidate(ContractModel):
    id: UUID = Field(default_factory=uuid4)
    request_revision_id: UUID
    lot_id: UUID
    supplier: Supplier
    offering_name: str = Field(min_length=2, max_length=300)
    source_url: str = Field(min_length=8, max_length=2048)
    quoted_price: Money | None = None
    attributes: dict[str, ScalarValue] = Field(default_factory=dict)
