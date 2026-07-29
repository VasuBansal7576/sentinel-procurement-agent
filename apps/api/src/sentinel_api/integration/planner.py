"""Category-generic typed intake and Temporal work planning."""

from __future__ import annotations

from decimal import Decimal
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from sentinel_api.application.walking_skeleton import CreateRunRequest
from sentinel_api.domain import (
    CategoryField,
    CategorySchema,
    Criterion,
    CriterionOperator,
    CriterionType,
    LineItem,
    Lot,
    ProcurementCase,
    ProcurementCaseStatus,
    Quantity,
    RequestRevision,
    Requirement,
    RequirementPriority,
    utc_now,
)
from sentinel_api.integration.models import IntegrationRecord
from sentinel_api.workflows.models import ProcurementRunInput, WorkItem


def deterministic_id(run_id: UUID, key: str) -> UUID:
    """Return an opaque, stable ID scoped to one non-guessable run UUID."""

    return uuid5(NAMESPACE_URL, f"sentinel:{run_id}:{key}")


def normalize_intake(
    request: CreateRunRequest,
    *,
    run_id: UUID | None = None,
) -> tuple[ProcurementCase, RequestRevision, ProcurementRunInput, IntegrationRecord]:
    """Normalize a generic request and produce one bounded end-to-end child."""

    owner_id = run_id or uuid4()
    case_id = deterministic_id(owner_id, "case")
    line_item_id = deterministic_id(owner_id, "line-item")
    lot_id = deterministic_id(owner_id, "lot")
    revision_id = deterministic_id(owner_id, "request-revision:1")
    category = CategorySchema(
        id=deterministic_id(owner_id, "category-schema"),
        name="Operator supplied category",
        fields=(
            CategoryField(
                key="description",
                label="Description",
                type=CriterionType.TEXT,
                required=True,
                description="Operator supplied category-neutral scope",
            ),
        ),
    )
    requirements = (
        Requirement(
            id=deterministic_id(owner_id, "requirement:availability"),
            key="availability",
            label="Available offering",
            description="Supplier confirms that the requested offering is available",
            subject_path=f"line_items.{line_item_id}.availability",
            priority=RequirementPriority.MANDATORY,
            criterion=Criterion(
                type=CriterionType.BOOLEAN,
                operator=CriterionOperator.EQUALS,
                target=True,
            ),
            acceptable_evidence=("supplier_page",),
        ),
        Requirement(
            id=deterministic_id(owner_id, "requirement:lead_time"),
            key="lead_time",
            label="Lead time",
            description="Delivery or mobilization within thirty calendar days",
            subject_path=f"line_items.{line_item_id}.lead_time",
            priority=RequirementPriority.MANDATORY,
            criterion=Criterion(
                type=CriterionType.NUMBER,
                operator=CriterionOperator.AT_MOST,
                target=Decimal("30"),
                unit="day",
            ),
            acceptable_evidence=("supplier_page",),
        ),
        Requirement(
            id=deterministic_id(owner_id, "requirement:unit_price"),
            key="unit_price",
            label="Unit price",
            description="Comparable credential-free indicative unit price",
            subject_path=f"line_items.{line_item_id}.unit_price",
            priority=RequirementPriority.PREFERRED,
            criterion=Criterion(
                type=CriterionType.MONEY,
                operator=CriterionOperator.AT_MOST,
                target=Decimal("1000"),
                currency="USD",
            ),
            acceptable_evidence=("supplier_page",),
        ),
    )
    revision = RequestRevision(
        id=revision_id,
        case_id=case_id,
        revision_number=1,
        reason="Initial operator request",
        lots=(
            Lot(
                id=lot_id,
                name="Primary lot",
                line_items=(
                    LineItem(
                        id=line_item_id,
                        name=request.item_name,
                        description=request.description,
                        quantity=Quantity(value=request.quantity, unit=request.unit),
                        category_schema=category,
                        requirements=requirements,
                    ),
                ),
            ),
        ),
    )
    now = utc_now()
    case = ProcurementCase(
        id=case_id,
        organization_id=deterministic_id(owner_id, "organization"),
        title=request.title,
        status=ProcurementCaseStatus.RUNNING,
        current_revision_id=revision.id,
        created_at=now,
        updated_at=now,
    )
    input_ref = deterministic_id(owner_id, "input")
    work = WorkItem(
        work_item_id=str(deterministic_id(owner_id, "work:end-to-end")),
        child_run_id=str(deterministic_id(owner_id, "child:end-to-end")),
        subagent_id=str(deterministic_id(owner_id, "subagent:end-to-end")),
        phase="integration",
        kind="end_to_end",
        label="Research, evaluate, and prepare",
        goal="Produce sourced comparison artifacts and an approval-bound RFQ proposal",
        input_ref=f"record://{input_ref}",
        output_keys=(
            "evidence:verified",
            "evaluation:ranking",
            "artifact:deliverables",
            "proposal:rfq",
        ),
        depends_on=(
            "request:scope",
            "request:quantity",
            "request:requirements",
            "policy:revision",
        ),
        tool_scope=(
            "research.snapshot",
            "research.extract",
            "evaluation.deterministic",
            "artifact.generate",
            "proposal.prepare",
        ),
        timeout_seconds=120,
    )
    runtime_input = ProcurementRunInput(
        run_id=str(owner_id),
        request_revision_id=str(revision.id),
        request_revision_number=revision.revision_number,
        policy_revision=1,
        title=request.title,
        work_items=(work,),
        max_concurrency=1,
    )
    record = IntegrationRecord(
        run_id=owner_id,
        record_ref=input_ref,
        record_kind="request",
        payload={
            "case": case.model_dump(mode="json"),
            "revision": revision.model_dump(mode="json"),
            "intake": request.model_dump(mode="json"),
        },
    )
    return case, revision, runtime_input, record
