"""Deterministic dependency invalidation across request revisions."""

from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import Field

from sentinel_api.domain.common import ContractModel


class WorkProductKind(StrEnum):
    RAW_EVIDENCE = "raw_evidence"
    OBSERVATION = "observation"
    EVALUATION = "evaluation"
    RANKING = "ranking"
    ARTIFACT = "artifact"
    PROPOSAL = "proposal"
    APPROVAL = "approval"


class WorkProduct(ContractModel):
    id: UUID = Field(default_factory=uuid4)
    kind: WorkProductKind
    output_key: str = Field(min_length=3, max_length=300)
    request_revision_number: int = Field(ge=1)
    policy_revision: int = Field(ge=1)
    depends_on: frozenset[str] = Field(default_factory=frozenset)


class InvalidatedProduct(ContractModel):
    product_id: UUID
    output_key: str
    reason_dependencies: frozenset[str]


class InvalidationPlan(ContractModel):
    retained_product_ids: tuple[UUID, ...]
    invalidated: tuple[InvalidatedProduct, ...]


def plan_invalidation(
    products: tuple[WorkProduct, ...],
    changed_dependencies: frozenset[str],
) -> InvalidationPlan:
    """Invalidate direct and transitive dependants while preserving unrelated work."""

    invalid_dependencies = set(changed_dependencies)
    invalidated: list[InvalidatedProduct] = []
    pending = list(products)

    made_progress = True
    while pending and made_progress:
        made_progress = False
        retained_pending: list[WorkProduct] = []
        for product in pending:
            matched = product.depends_on & invalid_dependencies
            if matched:
                invalidated.append(
                    InvalidatedProduct(
                        product_id=product.id,
                        output_key=product.output_key,
                        reason_dependencies=frozenset(matched),
                    )
                )
                invalid_dependencies.add(product.output_key)
                made_progress = True
            else:
                retained_pending.append(product)
        pending = retained_pending

    return InvalidationPlan(
        retained_product_ids=tuple(product.id for product in pending),
        invalidated=tuple(invalidated),
    )
