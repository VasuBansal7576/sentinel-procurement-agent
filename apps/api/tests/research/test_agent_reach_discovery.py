"""Unit tests for Agent Reach parsing and discovery mapping."""

from uuid import uuid4

import pytest

from sentinel_api.research.agent_reach import (
    FakeResearchClient,
    _parse_exa_markdown,
    discover_sources,
)
from sentinel_api.research.discovery import candidate_from_source, extract_facts


def test_parse_exa_markdown_extracts_title_url_and_snippet() -> None:
    raw = """
Title: Acme Pump Co sanitary 316L pump
URL: https://www.acmepump.example/products/316l
Published: N/A
Author: N/A
Highlights:
Acme Pump Co sells food-grade 316L transfer pumps.
Lead time 12 days. Available for bulk order.
...
---

Title: Beta Supply transfer equipment
URL: https://beta.example/pumps
Highlights:
Beta Supply wholesale pumps.
"""
    hits = _parse_exa_markdown(raw, limit=5)
    assert len(hits) == 2
    assert str(hits[0].url).startswith("https://www.acmepump.example/")
    assert "Acme" in hits[0].title.value
    assert "Lead time" in hits[0].snippet.value


@pytest.mark.asyncio
async def test_fake_research_discover_sources_returns_pages() -> None:
    client = FakeResearchClient()
    sources = await discover_sources(
        client,
        item_name="transfer pump",
        description="316L sanitary",
        limit=3,
    )
    assert len(sources) == 3
    assert all(source.page_text for source in sources)
    facts = extract_facts(sources[0], item_name="transfer pump")
    assert facts.available is True
    assert facts.lead_time_days > 0
    candidate = candidate_from_source(
        run_id=uuid4(),
        position=1,
        request_revision_id=uuid4(),
        lot_id=uuid4(),
        item_name="transfer pump",
        description="316L",
        source=sources[0],
        facts=facts,
    )
    assert candidate.supplier.legal_name
    assert str(candidate.source_url).startswith("https://")
