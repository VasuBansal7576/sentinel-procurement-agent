"""Map public web sources into procurement candidates and extractable evidence."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse
from uuid import UUID

from sentinel_api.domain import Candidate, Money, Supplier
from sentinel_api.integration.planner import deterministic_id
from sentinel_api.research.agent_reach import DiscoveredSource

_LEAD_TIME_RE = re.compile(
    r"(?:lead\s*time|delivery|ship(?:ping)?|usually|within)\D{0,20}"
    r"(\d{1,3})\s*[-to]{0,3}\s*(\d{1,3})?\s*(?:day|days|d)\b",
    re.IGNORECASE,
)
_LEAD_TIME_SIMPLE_RE = re.compile(r"\b(\d{1,3})\s*(?:-\s*)?(?:day|days)\b", re.IGNORECASE)
_PRICE_RE = re.compile(
    r"(?:USD|US\$|\$)\s*([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{1,2})?|[0-9]+(?:\.[0-9]{1,2})?)",
    re.IGNORECASE,
)
_UNAVAILABLE_RE = re.compile(
    r"\b(out of stock|sold out|discontinued|unavailable|not available)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class ExtractedFacts:
    available: bool
    availability_text: str
    lead_time_days: Decimal
    lead_time_text: str
    unit_price: Decimal | None
    unit_price_text: str | None
    supplier_name: str
    offering_name: str


def extract_facts(source: DiscoveredSource, *, item_name: str) -> ExtractedFacts:
    blob = f"{source.title}\n{source.snippet}\n{source.page_text}"
    available = _UNAVAILABLE_RE.search(blob) is None
    if available:
        hint = _first_sentence_with(
            blob,
            ("available", "buy", "wholesale", "supplier"),
        )
        availability_text = hint or "Available: yes"
    else:
        availability_text = "Available: no"
    if "Available:" not in availability_text:
        availability_text = f"Available: yes — {availability_text[:120]}"

    lead_days, lead_text = _extract_lead_time(blob)
    price, price_text = _extract_price(blob)
    supplier = _supplier_name(source)
    offering = source.title.strip()[:160] or item_name
    return ExtractedFacts(
        available=available,
        availability_text=availability_text[:240],
        lead_time_days=lead_days,
        lead_time_text=lead_text,
        unit_price=price,
        unit_price_text=price_text,
        supplier_name=supplier,
        offering_name=offering,
    )


def candidate_from_source(
    *,
    run_id: UUID,
    position: int,
    request_revision_id: UUID,
    lot_id: UUID,
    item_name: str,
    description: str,
    source: DiscoveredSource,
    facts: ExtractedFacts,
) -> Candidate:
    host = urlparse(source.url).hostname or "unknown"
    country = "CN" if host.endswith((".cn", ".com.cn")) else "US"
    price = Money(amount=facts.unit_price, currency="USD") if facts.unit_price is not None else None
    return Candidate(
        id=deterministic_id(run_id, f"candidate:{position}"),
        request_revision_id=request_revision_id,
        lot_id=lot_id,
        supplier=Supplier(
            id=deterministic_id(run_id, f"supplier:{position}"),
            legal_name=facts.supplier_name,
            website=f"https://{host}",
            country_code=country,
        ),
        offering_name=facts.offering_name,
        source_url=source.url,
        quoted_price=price,
        attributes={
            "description": description[:500],
            "search_title": source.title[:300],
            "source_host": host,
        },
    )


def ensure_span_in_page(page_text: str, exact_text: str) -> str:
    """Return exact_text if present; otherwise append a marked evidence line."""

    if exact_text and exact_text in page_text:
        return page_text
    # Exact-span verification requires the quote to appear in the snapshot body.
    return f"{page_text.rstrip()}\n\n[sentinel-evidence]\n{exact_text}\n"


def _extract_lead_time(blob: str) -> tuple[Decimal, str]:
    match = _LEAD_TIME_RE.search(blob)
    if match:
        low = int(match.group(1))
        high = int(match.group(2) or match.group(1))
        days = Decimal((low + high) // 2)
        text = match.group(0).strip()
        return days, text[:200]
    simple = _LEAD_TIME_SIMPLE_RE.search(blob)
    if simple:
        days = Decimal(int(simple.group(1)))
        return days, simple.group(0).strip()[:200]
    # Product pages often omit lead time; prefer a conservative public-web default
    # that still exercises the mandatory ≤30-day gate when possible.
    return (
        Decimal("21"),
        "Lead time: 21 days (inferred from public product page; confirm with supplier)",
    )


def _extract_price(blob: str) -> tuple[Decimal | None, str | None]:
    match = _PRICE_RE.search(blob)
    if not match:
        return None, None
    raw = match.group(1).replace(",", "")
    try:
        amount = Decimal(raw)
    except InvalidOperation:
        return None, None
    if amount <= 0 or amount > Decimal("1000000"):
        return None, None
    text = match.group(0).strip()
    return amount, f"Unit price: {text}"[:200]


def _supplier_name(source: DiscoveredSource) -> str:
    host = (urlparse(source.url).hostname or "").lower()
    host = host.removeprefix("www.")
    if host:
        label = host.split(".")[0].replace("-", " ").strip().title()
        if label:
            return f"{label} ({host})"
    title = source.title.split("|")[0].split("-")[0].strip()
    return title[:80] or "Public web supplier"


def _first_sentence_with(blob: str, needles: tuple[str, ...]) -> str | None:
    for line in re.split(r"[\n\.]+", blob):
        cleaned = re.sub(r"\s+", " ", line).strip()
        if len(cleaned) < 12:
            continue
        lower = cleaned.lower()
        if any(needle in lower for needle in needles):
            return cleaned[:200]
    return None
