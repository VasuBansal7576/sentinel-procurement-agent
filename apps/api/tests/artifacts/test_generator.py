import csv
import io
import zipfile
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID
from xml.etree import ElementTree

from sentinel_api.artifacts import (
    generate_artifact_set,
    generate_comparison_workbook,
    generate_recommendation_report,
    generate_requirements_specification,
    generate_rfq_package,
)
from sentinel_api.domain import (
    ArtifactKind,
    Candidate,
    CategoryField,
    CategorySchema,
    Criterion,
    CriterionOperator,
    CriterionType,
    EvidenceClassification,
    EvidenceObservation,
    LineItem,
    Lot,
    Quantity,
    RequestRevision,
    Requirement,
    RequirementPriority,
    Supplier,
)
from sentinel_api.evaluation import RankingResult, evaluate_candidate, rank_candidates

AS_OF = datetime(2026, 7, 29, 12, tzinfo=UTC)
REVISION_ID = UUID(int=501)
LOT_ID = UUID(int=502)


def fixture() -> tuple[RequestRevision, Candidate, tuple[EvidenceObservation, ...]]:
    requirements = (
        Requirement(
            id=UUID(int=510),
            key="recycled_content",
            label="Recycled | content",
            description="At least 80% recycled material\nby weight",
            subject_path="attributes.recycled_content",
            priority=RequirementPriority.MANDATORY,
            acceptable_evidence=("manufacturer declaration",),
            criterion=Criterion(
                type=CriterionType.NUMBER,
                operator=CriterionOperator.AT_LEAST,
                target=Decimal("80"),
                unit="percent",
            ),
        ),
        Requirement(
            id=UUID(int=511),
            key="printable",
            label="Printable",
            description="Accepts custom printing",
            subject_path="attributes.printable",
            priority=RequirementPriority.PREFERRED,
            criterion=Criterion(
                type=CriterionType.ENUM,
                operator=CriterionOperator.IN,
                target="supplier response",
                allowed_values=("screen", "digital"),
                weight=Decimal("2"),
            ),
        ),
    )
    revision = RequestRevision(
        id=REVISION_ID,
        case_id=UUID(int=503),
        revision_number=1,
        reason="Packaging procurement",
        lots=(
            Lot(
                id=LOT_ID,
                name="Mailer boxes",
                line_items=(
                    LineItem(
                        id=UUID(int=504),
                        name="Small mailers",
                        description="Recycled corrugated mailer boxes",
                        quantity=Quantity(value=Decimal("1000"), unit="each"),
                        category_schema=CategorySchema(
                            id=UUID(int=505),
                            name="Packaging",
                            fields=(
                                CategoryField(
                                    key="recycled_content",
                                    label="Recycled content",
                                    type=CriterionType.NUMBER,
                                    unit="percent",
                                    required=True,
                                    description="Recycled material percentage",
                                ),
                            ),
                        ),
                        requirements=requirements,
                    ),
                ),
            ),
        ),
    )
    candidate = Candidate(
        id=UUID(int=506),
        request_revision_id=revision.id,
        lot_id=LOT_ID,
        supplier=Supplier(id=UUID(int=507), legal_name="Box & Board Co."),
        offering_name="Eco | Mailer",
        source_url="https://boxes.example/mailer",
    )
    observations = (
        EvidenceObservation(
            id=UUID(int=520),
            request_revision_id=revision.id,
            candidate_id=candidate.id,
            requirement_key="recycled_content",
            evidence_type="manufacturer declaration",
            value=Decimal("85"),
            normalized_unit="percent",
            classification=EvidenceClassification.OBSERVED,
            extractor_version="test",
            confidence=0.9,
        ),
        EvidenceObservation(
            id=UUID(int=521),
            request_revision_id=revision.id,
            candidate_id=candidate.id,
            requirement_key="printable",
            value=None,
            classification=EvidenceClassification.UNKNOWN,
            extractor_version="test",
            confidence=0,
        ),
    )
    return revision, candidate, observations


def ranking_fixture() -> tuple[RequestRevision, Candidate, RankingResult]:
    revision, candidate, observations = fixture()
    requirements = revision.lots[0].line_items[0].requirements
    evaluation = evaluate_candidate(
        candidate,
        requirements,
        observations,
        as_of=AS_OF,
    )
    return revision, candidate, rank_candidates((evaluation,))


def test_requirements_specification_is_complete_escaped_and_deterministic() -> None:
    revision, _, _ = fixture()

    first = generate_requirements_specification(revision)
    second = generate_requirements_specification(revision)
    text = first.content.decode()

    assert first == second
    assert first.kind is ArtifactKind.REQUIREMENTS_SPECIFICATION
    assert first.filename == "requirements-revision-1.md"
    assert "Recycled \\| content" in text
    assert "At least 80% recycled material by weight" in text
    assert "manufacturer declaration" in text
    assert "in [screen, digital]" in text
    assert first.sha256 == second.sha256


def test_comparison_workbook_is_valid_minimal_xlsx_with_evidence_rows() -> None:
    _, candidate, ranking = ranking_fixture()

    workbook = generate_comparison_workbook(ranking)

    assert workbook.kind is ArtifactKind.COMPARISON_WORKBOOK
    assert workbook.content[:2] == b"PK"
    with zipfile.ZipFile(io.BytesIO(workbook.content)) as archive:
        assert set(archive.namelist()) == {
            "[Content_Types].xml",
            "_rels/.rels",
            "xl/workbook.xml",
            "xl/_rels/workbook.xml.rels",
            "xl/worksheets/sheet1.xml",
            "xl/worksheets/sheet2.xml",
        }
        ElementTree.fromstring(archive.read("xl/worksheets/sheet1.xml"))
        ElementTree.fromstring(archive.read("xl/worksheets/sheet2.xml"))
        summary = ElementTree.fromstring(archive.read("xl/worksheets/sheet1.xml"))
        assert candidate.supplier.legal_name in "".join(summary.itertext())
        evidence_xml = archive.read("xl/worksheets/sheet2.xml")
        assert b"recycled_content" in evidence_xml
        assert b"unknown" in evidence_xml


def test_recommendation_report_discloses_unknown_evidence() -> None:
    revision, candidate, ranking = ranking_fixture()

    report = generate_recommendation_report(revision, ranking)
    text = report.content.decode()

    assert report.kind is ArtifactKind.RECOMMENDATION_REPORT
    assert f"Recommend **{candidate.offering_name.replace('|', chr(92) + '|')}**" in text
    assert "printable: unknown" in text
    assert "Evidence coverage: 50%" in text


def test_report_refuses_to_recommend_an_ineligible_candidate() -> None:
    revision, candidate, _ = fixture()
    mandatory = revision.lots[0].line_items[0].requirements[0]
    failed = EvidenceObservation(
        id=UUID(int=530),
        request_revision_id=revision.id,
        candidate_id=candidate.id,
        requirement_key=mandatory.key,
        value=Decimal("20"),
        normalized_unit="percent",
        classification=EvidenceClassification.OBSERVED,
        extractor_version="test",
        confidence=1,
    )
    ranking = rank_candidates(
        (
            evaluate_candidate(
                candidate,
                (mandatory,),
                (failed,),
                as_of=AS_OF,
            ),
        )
    )

    report = generate_recommendation_report(revision, ranking).content.decode()

    assert ranking.recommended_candidate_id is None
    assert "No candidate is currently eligible" in report


def test_rfq_package_contains_neutral_email_requirements_and_response_template() -> None:
    revision, candidate, _ = fixture()

    package = generate_rfq_package(revision, (candidate,))

    assert package.kind is ArtifactKind.RFQ_PACKAGE
    with zipfile.ZipFile(io.BytesIO(package.content)) as archive:
        assert archive.namelist() == [
            "email-body.txt",
            "requirements.md",
            "supplier-response.csv",
        ]
        email = archive.read("email-body.txt").decode()
        assert candidate.supplier.legal_name in email
        assert "does not authorize an external send or purchase" in email
        rows = list(csv.DictReader(io.StringIO(archive.read("supplier-response.csv").decode())))
        assert len(rows) == 2
        assert rows[0]["requirement_key"] == "recycled_content"
        assert rows[0]["response"] == ""


def test_rfq_csv_neutralizes_spreadsheet_formula_fields() -> None:
    revision, _, _ = fixture()
    original_lot = revision.lots[0]
    original_item = original_lot.line_items[0]
    dangerous_requirement = original_item.requirements[0].model_copy(
        update={"description": '=WEBSERVICE("bad")'}
    )
    dangerous_item = original_item.model_copy(
        update={
            "requirements": (
                dangerous_requirement,
                *original_item.requirements[1:],
            )
        }
    )
    dangerous_lot = original_lot.model_copy(update={"line_items": (dangerous_item,)})
    dangerous_revision = revision.model_copy(update={"lots": (dangerous_lot,)})

    package = generate_rfq_package(dangerous_revision)

    with zipfile.ZipFile(io.BytesIO(package.content)) as archive:
        rows = list(csv.DictReader(io.StringIO(archive.read("supplier-response.csv").decode())))
    assert rows[0]["requirement"] == '\'=WEBSERVICE("bad")'


def test_complete_artifact_set_and_archives_are_byte_stable() -> None:
    revision, _, ranking = ranking_fixture()

    first = generate_artifact_set(revision, ranking)
    second = generate_artifact_set(revision, ranking)

    assert [artifact.kind for artifact in first] == [
        ArtifactKind.REQUIREMENTS_SPECIFICATION,
        ArtifactKind.COMPARISON_WORKBOOK,
        ArtifactKind.RECOMMENDATION_REPORT,
        ArtifactKind.RFQ_PACKAGE,
    ]
    assert [artifact.content for artifact in first] == [artifact.content for artifact in second]
    assert all(artifact.size_bytes > 0 for artifact in first)
    assert all(len(artifact.sha256) == 64 for artifact in first)


def test_generated_payload_instantiates_the_central_artifact_contract() -> None:
    revision, _, _ = fixture()
    generated = generate_requirements_specification(revision)

    artifact = generated.to_domain_artifact(
        run_id=UUID(int=540),
        request_revision_id=revision.id,
        object_key=f"runs/540/{generated.filename}",
    )

    assert artifact.kind is generated.kind
    assert artifact.sha256 == generated.sha256
    assert artifact.size_bytes == len(generated.content)
    assert artifact.request_revision_id == revision.id
