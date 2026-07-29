"""Render byte-stable procurement deliverables without credentials or external services."""

import csv
import hashlib
import io
import zipfile
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID
from xml.sax.saxutils import escape as xml_escape

from sentinel_api.domain.artifacts import Artifact, ArtifactKind
from sentinel_api.domain.common import ScalarValue
from sentinel_api.domain.procurement import Candidate, CriterionOperator, RequestRevision
from sentinel_api.evaluation.models import (
    CandidateEvaluation,
    EvaluationStatus,
    RankingResult,
)

_PRODUCER = "sentinel.deterministic-artifact-engine/1.0.0"
_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)


@dataclass(frozen=True)
class GeneratedArtifact:
    """Complete in-memory artifact ready for object storage and domain registration."""

    kind: ArtifactKind
    filename: str
    media_type: str
    content: bytes

    @property
    def size_bytes(self) -> int:
        return len(self.content)

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.content).hexdigest()

    def to_domain_artifact(
        self,
        *,
        run_id: UUID,
        request_revision_id: UUID,
        object_key: str,
        version: int = 1,
        producer: str = _PRODUCER,
        approval_version: int | None = None,
        immutable: bool = False,
    ) -> Artifact:
        return Artifact(
            version=version,
            kind=self.kind,
            object_key=object_key,
            media_type=self.media_type,
            size_bytes=self.size_bytes,
            sha256=self.sha256,
            run_id=run_id,
            request_revision_id=request_revision_id,
            producer=producer,
            approval_version=approval_version,
            immutable=immutable,
        )


def _markdown(value: str) -> str:
    return value.replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ")


def _display(value: ScalarValue) -> str:
    if value is None:
        return "unknown"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, Decimal):
        rendered = format(value, "f")
        if "." in rendered:
            rendered = rendered.rstrip("0").rstrip(".")
        return rendered or "0"
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _criterion_text(
    operator: CriterionOperator,
    target: ScalarValue,
    unit: str | None,
    allowed_values: tuple[str, ...],
) -> str:
    if operator is CriterionOperator.IN:
        allowed = ", ".join(allowed_values) or "no configured values"
        return f"in [{allowed}]"
    target_text = "" if operator is CriterionOperator.EXISTS else f" {_display(target)}"
    unit_text = f" {unit}" if unit else ""
    return f"{operator.value.replace('_', ' ')}{target_text}{unit_text}".strip()


def _requirements_markdown(revision: RequestRevision) -> str:
    lines = [
        "# Requirements specification",
        "",
        f"Request revision: {revision.revision_number}",
        "",
        revision.reason,
        "",
    ]
    for lot in revision.lots:
        lines.extend((f"## Lot: {_markdown(lot.name)}", ""))
        for line_item in lot.line_items:
            quantity = f"{_display(line_item.quantity.value)} {line_item.quantity.unit}"
            lines.extend(
                (
                    f"### {_markdown(line_item.name)}",
                    "",
                    _markdown(line_item.description),
                    "",
                    f"Quantity: {quantity}",
                    "",
                    "| Key | Requirement | Priority | Criterion | Acceptable evidence |",
                    "|---|---|---|---|---|",
                )
            )
            if not line_item.requirements:
                lines.append("| — | No explicit requirements | informational | — | — |")
            for requirement in line_item.requirements:
                criterion = requirement.criterion
                unit = criterion.unit or criterion.currency
                acceptable = ", ".join(requirement.acceptable_evidence) or "not specified"
                description = f"{requirement.label}: {requirement.description}"
                lines.append(
                    "| "
                    + " | ".join(
                        (
                            _markdown(requirement.key),
                            _markdown(description),
                            requirement.priority.value,
                            _markdown(
                                _criterion_text(
                                    criterion.operator,
                                    criterion.target,
                                    unit,
                                    criterion.allowed_values,
                                )
                            ),
                            _markdown(acceptable),
                        )
                    )
                    + " |"
                )
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def generate_requirements_specification(revision: RequestRevision) -> GeneratedArtifact:
    content = _requirements_markdown(revision).encode()
    return GeneratedArtifact(
        kind=ArtifactKind.REQUIREMENTS_SPECIFICATION,
        filename=f"requirements-revision-{revision.revision_number}.md",
        media_type="text/markdown; charset=utf-8",
        content=content,
    )


def _column_name(index: int) -> str:
    result = ""
    current = index
    while current:
        current, remainder = divmod(current - 1, 26)
        result = chr(65 + remainder) + result
    return result


def _worksheet(rows: Sequence[Sequence[str]]) -> bytes:
    xml_rows: list[str] = []
    for row_index, row in enumerate(rows, start=1):
        cells = []
        for column_index, value in enumerate(row, start=1):
            reference = f"{_column_name(column_index)}{row_index}"
            escaped = xml_escape(value, {'"': "&quot;"})
            cells.append(
                f'<c r="{reference}" t="inlineStr"><is><t xml:space="preserve">'
                f"{escaped}</t></is></c>"
            )
        xml_rows.append(f'<row r="{row_index}">{"".join(cells)}</row>')
    xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f"<sheetData>{''.join(xml_rows)}</sheetData>"
        "</worksheet>"
    )
    return xml.encode()


def _zip_bytes(entries: Iterable[tuple[str, bytes]]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(
        output,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as archive:
        for filename, content in entries:
            info = zipfile.ZipInfo(filename, date_time=_ZIP_TIMESTAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 0
            info.external_attr = 0
            archive.writestr(info, content)
    return output.getvalue()


def _workbook_bytes(
    summary_rows: Sequence[Sequence[str]],
    evidence_rows: Sequence[Sequence[str]],
) -> bytes:
    content_types = (
        b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        b'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        b'<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.'
        b'relationships+xml"/>'
        b'<Default Extension="xml" ContentType="application/xml"/>'
        b'<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-'
        b'officedocument.spreadsheetml.sheet.main+xml"/>'
        b'<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.'
        b'openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        b'<Override PartName="/xl/worksheets/sheet2.xml" ContentType="application/vnd.'
        b'openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        b"</Types>"
    )
    root_relationships = (
        b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        b'<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/'
        b'2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
        b"</Relationships>"
    )
    workbook = (
        b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        b'<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        b'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        b'<sheets><sheet name="Comparison" sheetId="1" r:id="rId1"/>'
        b'<sheet name="Evidence" sheetId="2" r:id="rId2"/></sheets>'
        b"</workbook>"
    )
    workbook_relationships = (
        b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        b'<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/'
        b'2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
        b'<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/'
        b'2006/relationships/worksheet" Target="worksheets/sheet2.xml"/>'
        b"</Relationships>"
    )
    return _zip_bytes(
        (
            ("[Content_Types].xml", content_types),
            ("_rels/.rels", root_relationships),
            ("xl/workbook.xml", workbook),
            ("xl/_rels/workbook.xml.rels", workbook_relationships),
            ("xl/worksheets/sheet1.xml", _worksheet(summary_rows)),
            ("xl/worksheets/sheet2.xml", _worksheet(evidence_rows)),
        )
    )


def _summary_rows(ranking: RankingResult) -> list[list[str]]:
    rows = [
        [
            "Rank",
            "Candidate ID",
            "Supplier",
            "Offering",
            "Eligible",
            "Weighted score",
            "Evidence coverage",
            "Failed mandatory",
            "Unresolved mandatory",
        ]
    ]
    for ranked in ranking.candidates:
        evaluation = ranked.evaluation
        rows.append(
            [
                str(ranked.rank),
                str(evaluation.candidate.id),
                evaluation.candidate.supplier.legal_name,
                evaluation.candidate.offering_name,
                "yes" if evaluation.eligible else "no",
                _display(evaluation.score),
                f"{_display(evaluation.coverage.percent)}%",
                ", ".join(evaluation.failed_mandatory_keys),
                ", ".join(evaluation.unresolved_mandatory_keys),
            ]
        )
    return rows


def _evidence_rows(ranking: RankingResult) -> list[list[str]]:
    rows = [
        [
            "Candidate ID",
            "Supplier",
            "Requirement key",
            "Priority",
            "Status",
            "Value",
            "Normalized unit",
            "Reason",
            "Observation IDs",
        ]
    ]
    for ranked in ranking.candidates:
        candidate = ranked.evaluation.candidate
        for requirement in ranked.evaluation.requirements:
            rows.append(
                [
                    str(candidate.id),
                    candidate.supplier.legal_name,
                    requirement.requirement.key,
                    requirement.requirement.priority.value,
                    requirement.status.value,
                    _display(requirement.value),
                    requirement.normalized_unit or "",
                    requirement.reason,
                    ", ".join(str(identifier) for identifier in requirement.observation_ids),
                ]
            )
    return rows


def generate_comparison_workbook(ranking: RankingResult) -> GeneratedArtifact:
    content = _workbook_bytes(_summary_rows(ranking), _evidence_rows(ranking))
    return GeneratedArtifact(
        kind=ArtifactKind.COMPARISON_WORKBOOK,
        filename="candidate-comparison.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        content=content,
    )


def _candidate_issue_text(evaluation: CandidateEvaluation) -> str:
    issues = [
        requirement
        for requirement in evaluation.requirements
        if requirement.status not in {EvaluationStatus.SATISFIED, EvaluationStatus.NOT_SATISFIED}
        or (
            requirement.status is EvaluationStatus.NOT_SATISFIED
            and requirement.requirement.key in evaluation.failed_mandatory_keys
        )
    ]
    if not issues:
        return "None"
    return "; ".join(
        f"{issue.requirement.key}: {issue.status.value} ({issue.reason})" for issue in issues
    )


def generate_recommendation_report(
    revision: RequestRevision,
    ranking: RankingResult,
) -> GeneratedArtifact:
    lines = [
        "# Recommendation report",
        "",
        f"Request revision: {revision.revision_number}",
        "",
    ]
    recommended = next(
        (
            ranked
            for ranked in ranking.candidates
            if ranked.evaluation.candidate.id == ranking.recommended_candidate_id
        ),
        None,
    )
    if recommended is None:
        lines.extend(
            (
                "## Recommendation",
                "",
                "No candidate is currently eligible. Resolve mandatory failures or evidence gaps "
                "before making an award recommendation.",
                "",
            )
        )
    else:
        evaluation = recommended.evaluation
        lines.extend(
            (
                "## Recommendation",
                "",
                f"Recommend **{_markdown(evaluation.candidate.offering_name)}** from "
                f"**{_markdown(evaluation.candidate.supplier.legal_name)}**.",
                "",
                f"Weighted score: {_display(evaluation.score)} / 100",
                "",
                f"Evidence coverage: {_display(evaluation.coverage.percent)}%",
                "",
            )
        )

    lines.extend(
        (
            "## Candidate comparison",
            "",
            "| Rank | Supplier | Offering | Eligible | Score | Evidence coverage |",
            "|---:|---|---|---|---:|---:|",
        )
    )
    for ranked in ranking.candidates:
        evaluation = ranked.evaluation
        lines.append(
            f"| {ranked.rank} | {_markdown(evaluation.candidate.supplier.legal_name)} | "
            f"{_markdown(evaluation.candidate.offering_name)} | "
            f"{'yes' if evaluation.eligible else 'no'} | {_display(evaluation.score)} | "
            f"{_display(evaluation.coverage.percent)}% |"
        )
    lines.extend(("", "## Evidence gaps and conflicts", ""))
    if not ranking.candidates:
        lines.append("No candidates were evaluated.")
    else:
        for ranked in ranking.candidates:
            lines.append(
                f"- {_markdown(ranked.evaluation.candidate.offering_name)}: "
                f"{_markdown(_candidate_issue_text(ranked.evaluation))}"
            )
    content = ("\n".join(lines).rstrip() + "\n").encode()
    return GeneratedArtifact(
        kind=ArtifactKind.RECOMMENDATION_REPORT,
        filename="recommendation-report.md",
        media_type="text/markdown; charset=utf-8",
        content=content,
    )


def _rfq_csv(revision: RequestRevision) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(
        [
            "lot",
            "line_item",
            "quantity",
            "quantity_unit",
            "requirement_key",
            "requirement",
            "priority",
            "response",
        ]
    )
    for lot in revision.lots:
        for line_item in lot.line_items:
            if not line_item.requirements:
                writer.writerow(
                    [
                        _spreadsheet_text(lot.name),
                        _spreadsheet_text(line_item.name),
                        _display(line_item.quantity.value),
                        _spreadsheet_text(line_item.quantity.unit),
                        "",
                        "",
                        "",
                        "",
                    ]
                )
            for requirement in line_item.requirements:
                writer.writerow(
                    [
                        _spreadsheet_text(lot.name),
                        _spreadsheet_text(line_item.name),
                        _display(line_item.quantity.value),
                        _spreadsheet_text(line_item.quantity.unit),
                        _spreadsheet_text(requirement.key),
                        _spreadsheet_text(requirement.description),
                        requirement.priority.value,
                        "",
                    ]
                )
    return output.getvalue().encode()


def _spreadsheet_text(value: str) -> str:
    """Prevent user-authored CSV fields from becoming spreadsheet formulas."""

    if value.lstrip().startswith(("=", "+", "-", "@")):
        return f"'{value}"
    return value


def _rfq_email(revision: RequestRevision, candidates: Sequence[Candidate]) -> bytes:
    supplier_names = ", ".join(candidate.supplier.legal_name for candidate in candidates)
    audience = supplier_names or "Procurement contact"
    return (
        f"Subject: Request for quotation — revision {revision.revision_number}\n\n"
        f"To: {audience}\n\n"
        "Please provide a quotation against the attached requirements and response template. "
        "Include pricing currency, lead time, validity period, delivery terms, and evidence "
        "for every mandatory requirement. Mark unavailable or uncertain information explicitly; "
        "do not infer a response.\n\n"
        "This package is a draft and does not authorize an external send or purchase.\n"
    ).encode()


def generate_rfq_package(
    revision: RequestRevision,
    candidates: Sequence[Candidate] = (),
) -> GeneratedArtifact:
    content = _zip_bytes(
        (
            ("email-body.txt", _rfq_email(revision, candidates)),
            ("requirements.md", _requirements_markdown(revision).encode()),
            ("supplier-response.csv", _rfq_csv(revision)),
        )
    )
    return GeneratedArtifact(
        kind=ArtifactKind.RFQ_PACKAGE,
        filename=f"rfq-package-revision-{revision.revision_number}.zip",
        media_type="application/zip",
        content=content,
    )


def generate_artifact_set(
    revision: RequestRevision,
    ranking: RankingResult,
) -> tuple[GeneratedArtifact, ...]:
    """Generate the complete PR 6 deliverable set from one immutable input snapshot."""

    eligible_candidates = tuple(
        ranked.evaluation.candidate for ranked in ranking.candidates if ranked.evaluation.eligible
    )
    return (
        generate_requirements_specification(revision),
        generate_comparison_workbook(ranking),
        generate_recommendation_report(revision, ranking),
        generate_rfq_package(revision, eligible_candidates),
    )
