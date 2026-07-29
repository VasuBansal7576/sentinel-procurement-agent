from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from sentinel_api.domain import ArtifactKind, EvidenceClassification, EvidenceObservation
from sentinel_api.research import (
    ClaimProvenance,
    EvidenceSnapshot,
    ExactSpan,
    FreshnessState,
    InMemorySnapshotStore,
    UntrustedContent,
    build_verified_observation,
    find_conflicts,
    freshness_at,
    locate_exact_span,
)


@pytest.mark.asyncio
async def test_fetch_snapshot_to_verified_observation_preserves_exact_provenance() -> None:
    run_id = uuid4()
    revision_id = uuid4()
    candidate_id = uuid4()
    body = b"<table><tr><td>Price</td><td>USD 12.50</td></tr></table>"
    content = UntrustedContent.from_body(
        url="https://example.com/product",
        body=body,
        media_type="text/html",
        retrieved_at=datetime(2026, 7, 29, 10, tzinfo=UTC),
    )
    store = InMemorySnapshotStore()
    snapshot = await store.put(
        run_id=run_id,
        request_revision_id=revision_id,
        producer="fetch.public_http@1.0.0",
        content=content,
    )

    verified = build_verified_observation(
        snapshot=snapshot,
        request_revision_id=revision_id,
        candidate_id=candidate_id,
        requirement_key="unit_price",
        value=Decimal("12.50"),
        normalized_unit="USD/item",
        exact_text="USD 12.50",
        extractor_version="price-table@1.0.0",
        confidence=0.99,
        fresh_until=datetime(2026, 7, 30, 10, tzinfo=UTC),
    )
    loaded = await store.get(snapshot.artifact.id)

    assert loaded == snapshot
    assert snapshot.artifact.immutable is True
    assert snapshot.artifact.object_key.endswith(content.content_sha256)
    assert verified.observation.source is not None
    assert verified.observation.source.response_artifact_id == snapshot.artifact.id
    assert verified.observation.source.content_sha256 == content.content_sha256
    assert verified.observation.source.exact_span == "USD 12.50"
    assert verified.provenance.span.start == body.decode().index("USD 12.50")
    assert verified.provenance.span.end - verified.provenance.span.start == len("USD 12.50")


@pytest.mark.asyncio
async def test_snapshot_store_deduplicates_bytes_but_issues_revision_bound_artifacts() -> None:
    content = UntrustedContent.from_body(
        url="https://example.com/product",
        body=b"stable specification",
        media_type="text/plain",
    )
    store = InMemorySnapshotStore()
    first = await store.put(
        run_id=uuid4(),
        request_revision_id=uuid4(),
        producer="fetch@1",
        content=content,
    )
    second = await store.put(
        run_id=uuid4(),
        request_revision_id=uuid4(),
        producer="fetch@1",
        content=content,
    )

    assert first.artifact.id != second.artifact.id
    assert first.artifact.object_key == second.artifact.object_key
    assert first.artifact.sha256 == second.artifact.sha256


@pytest.mark.asyncio
async def test_altered_or_wrong_revision_content_cannot_support_a_claim() -> None:
    revision_id = uuid4()
    content = UntrustedContent.from_body(
        url="https://example.com/product",
        body=b"Price USD 12.50",
        media_type="text/plain",
    )
    snapshot = await InMemorySnapshotStore().put(
        run_id=uuid4(),
        request_revision_id=revision_id,
        producer="fetch@1",
        content=content,
    )

    with pytest.raises(ValueError, match="does not occur"):
        locate_exact_span(snapshot, "USD 9.99")
    with pytest.raises(ValueError, match="cannot be empty"):
        locate_exact_span(snapshot, "")
    with pytest.raises(ValueError, match="cannot be negative"):
        locate_exact_span(snapshot, "USD 12.50", occurrence=-1)
    with pytest.raises(ValueError, match="different request revision"):
        build_verified_observation(
            snapshot=snapshot,
            request_revision_id=uuid4(),
            candidate_id=None,
            requirement_key="unit_price",
            value=Decimal("12.50"),
            exact_text="USD 12.50",
            extractor_version="extractor@1",
            confidence=0.9,
        )

    with pytest.raises(ValidationError, match="digest"):
        EvidenceSnapshot(
            artifact=snapshot.artifact.model_copy(update={"sha256": "0" * 64}),
            content=snapshot.content,
        )


@pytest.mark.asyncio
async def test_snapshot_artifact_binding_checks_kind_size_media_and_missing_ids() -> None:
    store = InMemorySnapshotStore()
    snapshot = await store.put(
        run_id=uuid4(),
        request_revision_id=uuid4(),
        producer="fetch@1",
        content=UntrustedContent.from_body(
            url="https://example.com/item",
            body=b"source",
            media_type="text/plain",
        ),
    )

    invalid_updates = (
        {"kind": ArtifactKind.SCREENSHOT},
        {"size_bytes": 999},
        {"media_type": "application/pdf"},
    )
    for update in invalid_updates:
        with pytest.raises(ValidationError, match="snapshot artifact"):
            EvidenceSnapshot(
                artifact=snapshot.artifact.model_copy(update=update),
                content=snapshot.content,
            )

    with pytest.raises(KeyError, match="not found"):
        await store.get(uuid4())


@pytest.mark.asyncio
async def test_provenance_rejects_mismatched_span_hash_text_and_source() -> None:
    revision_id = uuid4()
    snapshot = await InMemorySnapshotStore().put(
        run_id=uuid4(),
        request_revision_id=revision_id,
        producer="fetch@1",
        content=UntrustedContent.from_body(
            url="https://example.com/item",
            body=b"first quote and second quote",
            media_type="text/plain",
        ),
    )
    first = build_verified_observation(
        snapshot=snapshot,
        request_revision_id=revision_id,
        candidate_id=None,
        requirement_key="specification",
        value="first",
        exact_text="quote",
        occurrence=0,
        extractor_version="extractor@1",
        confidence=0.8,
    )
    second_span = locate_exact_span(snapshot, "quote", occurrence=1)
    assert first.provenance.span.start != second_span.start

    with pytest.raises(ValidationError, match="span digest"):
        ExactSpan.model_validate({**first.provenance.span.model_dump(), "text_sha256": "0" * 64})

    with pytest.raises(ValidationError, match="different content"):
        ClaimProvenance(
            source=first.provenance.source,
            span=second_span.model_copy(update={"content_sha256": "0" * 64}),
        )


def _observation(
    value: object,
    *,
    revision_id: object,
    candidate_id: object,
    requirement_key: str = "lead_time",
    classification: EvidenceClassification = EvidenceClassification.OBSERVED,
) -> EvidenceObservation:
    return EvidenceObservation(
        request_revision_id=revision_id,
        candidate_id=candidate_id,
        requirement_key=requirement_key,
        evidence_type="supplier_page",
        value=value,
        classification=classification,
        extractor_version="test@1",
        confidence=0.9,
    )


def test_freshness_boundary_is_deterministic_and_timezone_safe() -> None:
    deadline = datetime(2026, 7, 29, 12, tzinfo=UTC)
    current = EvidenceObservation(
        request_revision_id=uuid4(),
        requirement_key="availability",
        value=True,
        classification=EvidenceClassification.OBSERVED,
        extractor_version="test@1",
        confidence=1,
        fresh_until=deadline,
    )
    unbounded = current.model_copy(update={"fresh_until": None})

    assert freshness_at(current, deadline) is FreshnessState.CURRENT
    assert freshness_at(current, deadline + timedelta(microseconds=1)) is FreshnessState.STALE
    assert freshness_at(unbounded, deadline + timedelta(days=100)) is FreshnessState.UNBOUNDED
    with pytest.raises(ValueError, match="timezone-aware"):
        freshness_at(current, datetime(2026, 7, 29, 12))


def test_conflicts_are_candidate_and_revision_scoped_and_resolvable() -> None:
    revision_id = uuid4()
    candidate_id = uuid4()
    first = _observation("5 days", revision_id=revision_id, candidate_id=candidate_id)
    second = _observation("8 days", revision_id=revision_id, candidate_id=candidate_id)
    sibling_candidate = _observation(
        "12 days",
        revision_id=revision_id,
        candidate_id=uuid4(),
    )
    unknown = _observation(
        None,
        revision_id=revision_id,
        candidate_id=candidate_id,
        classification=EvidenceClassification.UNKNOWN,
    )

    conflicts = find_conflicts((first, second, sibling_candidate, unknown))

    assert len(conflicts) == 1
    assert conflicts[0].conflict.observation_ids == (first.id, second.id)
    resolved = conflicts[0].resolve(second.id)
    assert resolved.conflict.resolved_by_observation_id == second.id
    with pytest.raises(ValueError, match="grouped observation"):
        conflicts[0].resolve(sibling_candidate.id)


def test_duplicate_values_do_not_create_a_conflict() -> None:
    revision_id = uuid4()
    candidate_id = uuid4()
    observations = (
        _observation("5 days", revision_id=revision_id, candidate_id=candidate_id),
        _observation("5 days", revision_id=revision_id, candidate_id=candidate_id),
    )

    assert find_conflicts(observations) == ()
