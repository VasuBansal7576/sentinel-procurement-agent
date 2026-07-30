"""Credential-free vertical slice used until durable adapters are integrated."""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import Field

from sentinel_api.domain import (
    ArtifactKind,
    AutonomyMode,
    CategoryField,
    CategorySchema,
    ContractModel,
    CriterionType,
    LineItem,
    Lot,
    ProcurementCase,
    ProcurementCaseStatus,
    Quantity,
    RequestRevision,
    utc_now,
)


class RunStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class CreateRunRequest(ContractModel):
    title: str = Field(min_length=3, max_length=200)
    item_name: str = Field(min_length=2, max_length=200)
    description: str = Field(min_length=3, max_length=2000)
    quantity: Decimal = Field(gt=0, max_digits=18, decimal_places=4)
    unit: str = Field(min_length=1, max_length=64)
    autonomy_mode: AutonomyMode = AutonomyMode.ASK_BEFORE_EXTERNAL


class RunEvent(ContractModel):
    event_id: UUID = Field(default_factory=uuid4)
    run_id: UUID
    sequence: int = Field(ge=1)
    event_type: str = Field(pattern=r"^[a-z][a-z0-9_.-]{2,99}$")
    status: str = Field(min_length=2, max_length=80)
    summary: str = Field(min_length=2, max_length=500)
    created_at: datetime = Field(default_factory=utc_now)


class ArtifactSummary(ContractModel):
    id: UUID
    kind: ArtifactKind
    filename: str
    media_type: str
    size_bytes: int = Field(ge=0)
    download_url: str


class RunView(ContractModel):
    id: UUID
    case_id: UUID
    request_revision_id: UUID
    title: str
    status: RunStatus
    current_phase: str
    created_at: datetime
    completed_at: datetime | None = None
    events: tuple[RunEvent, ...]
    artifacts: tuple[ArtifactSummary, ...]


@dataclass(frozen=True)
class StoredArtifact:
    summary: ArtifactSummary
    content: bytes


@dataclass
class StoredRun:
    id: UUID
    case: ProcurementCase
    revision: RequestRevision
    title: str
    status: RunStatus
    current_phase: str
    created_at: datetime
    completed_at: datetime | None = None
    events: list[RunEvent] = field(default_factory=list)
    artifacts: list[StoredArtifact] = field(default_factory=list)

    def to_view(self) -> RunView:
        return RunView(
            id=self.id,
            case_id=self.case.id,
            request_revision_id=self.revision.id,
            title=self.title,
            status=self.status,
            current_phase=self.current_phase,
            created_at=self.created_at,
            completed_at=self.completed_at,
            events=tuple(self.events),
            artifacts=tuple(artifact.summary for artifact in self.artifacts),
        )


class InMemoryRunStore:
    """Small adapter whose interface is replaced by PR 4 persistence."""

    def __init__(self) -> None:
        self._runs: dict[UUID, StoredRun] = {}

    def create(self, request: CreateRunRequest) -> RunView:
        run_id = uuid4()
        case_id = uuid4()
        schema = CategorySchema(
            name="Operator supplied category",
            fields=(
                CategoryField(
                    key="description",
                    label="Description",
                    type=CriterionType.TEXT,
                    required=True,
                    description="Operator supplied item or service description",
                ),
            ),
        )
        revision = RequestRevision(
            case_id=case_id,
            revision_number=1,
            reason="Initial operator request",
            lots=(
                Lot(
                    name="Primary lot",
                    line_items=(
                        LineItem(
                            name=request.item_name,
                            description=request.description,
                            quantity=Quantity(value=request.quantity, unit=request.unit),
                            category_schema=schema,
                        ),
                    ),
                ),
            ),
        )
        now = utc_now()
        case = ProcurementCase(
            id=case_id,
            organization_id=uuid4(),
            title=request.title,
            status=ProcurementCaseStatus.RUNNING,
            current_revision_id=revision.id,
            created_at=now,
            updated_at=now,
        )
        stored = StoredRun(
            id=run_id,
            case=case,
            revision=revision,
            title=request.title,
            status=RunStatus.RUNNING,
            current_phase="intake",
            created_at=now,
        )
        self._runs[run_id] = stored
        self._append_event(stored, "run.created", "running", "Procurement run created")
        self._append_event(
            stored,
            "request.normalized",
            "completed",
            f"Normalized {request.quantity} {request.unit} of {request.item_name}",
        )
        artifact = self._requirements_artifact(stored, request)
        stored.artifacts.append(artifact)
        self._append_event(
            stored,
            "artifact.created",
            "completed",
            f"Generated {artifact.summary.filename}",
        )
        stored.status = RunStatus.COMPLETED
        stored.current_phase = "intake complete"
        stored.completed_at = utc_now()
        stored.case = stored.case.model_copy(
            update={
                "status": ProcurementCaseStatus.COMPLETED,
                "updated_at": stored.completed_at,
            }
        )
        self._append_event(stored, "run.completed", "completed", "Walking skeleton completed")
        return stored.to_view()

    def list(self) -> tuple[RunView, ...]:
        return tuple(
            stored.to_view()
            for stored in sorted(
                self._runs.values(),
                key=lambda run: run.created_at,
                reverse=True,
            )
        )

    def get(self, run_id: UUID) -> RunView | None:
        stored = self._runs.get(run_id)
        return stored.to_view() if stored else None

    def events_after(self, run_id: UUID, sequence: int) -> tuple[RunEvent, ...] | None:
        stored = self._runs.get(run_id)
        if stored is None:
            return None
        return tuple(event for event in stored.events if event.sequence > sequence)

    def artifact(self, run_id: UUID, artifact_id: UUID) -> StoredArtifact | None:
        stored = self._runs.get(run_id)
        if stored is None:
            return None
        return next(
            (artifact for artifact in stored.artifacts if artifact.summary.id == artifact_id),
            None,
        )

    @staticmethod
    def _append_event(
        run: StoredRun,
        event_type: str,
        status: str,
        summary: str,
    ) -> None:
        run.events.append(
            RunEvent(
                run_id=run.id,
                sequence=len(run.events) + 1,
                event_type=event_type,
                status=status,
                summary=summary,
            )
        )

    @staticmethod
    def _requirements_artifact(
        run: StoredRun,
        request: CreateRunRequest,
    ) -> StoredArtifact:
        content = (
            f"# {request.title}\n\n"
            "## Initial requirements\n\n"
            f"- Item or service: {request.item_name}\n"
            f"- Description: {request.description}\n"
            f"- Quantity: {request.quantity} {request.unit}\n"
            f"- Request revision: {run.revision.revision_number}\n"
            "\nThis credential-free artifact proves the complete intake delivery path.\n"
        ).encode()
        artifact_id = uuid4()
        filename = f"requirements-{run.id}.md"
        summary = ArtifactSummary(
            id=artifact_id,
            kind=ArtifactKind.REQUIREMENTS_SPECIFICATION,
            filename=filename,
            media_type="text/markdown; charset=utf-8",
            size_bytes=len(content),
            download_url=f"/api/runs/{run.id}/artifacts/{artifact_id}",
        )
        return StoredArtifact(summary=summary, content=content)
