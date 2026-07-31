"""Agent-Reach style open research: free web search + page read without paid platform APIs.

Uses the same backends Agent Reach routes to on a healthy install:
  - Search: Exa via mcporter (`exa.web_search_exa`)
  - Read:   Jina Reader (`https://r.jina.ai/{url}`)

Falls back to DuckDuckGo HTML only if mcporter/Exa is unavailable.
"""

from __future__ import annotations

import asyncio
import json
import re
import subprocess
from dataclasses import dataclass
from html import unescape
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote_plus, unquote, urlparse
from urllib.request import Request, urlopen

from sentinel_api.research.models import (
    SearchHit,
    TaintedText,
    TaintLabel,
    UntrustedContent,
)

_USER_AGENT = (
    "SentinelProcurementAgent/1.0 (+https://github.com/VasuBansal7576/sentinel-procurement-agent)"
)
_TITLE_RE = re.compile(r"^Title:\s*(.+)\s*$", re.MULTILINE)
_URL_RE = re.compile(r"^URL:\s*(\S+)\s*$", re.MULTILINE)
_HIGHLIGHT_BLOCK_RE = re.compile(
    r"Highlights:\s*\n(.*?)(?=\n---|\nTitle:|\Z)",
    re.DOTALL | re.IGNORECASE,
)
_DDG_RESULT_RE = re.compile(
    r'uddg=([^&"]+).*?class="result__a"[^>]*>(.*?)</a>.*?'
    r'class="result__snippet"[^>]*>(.*?)</(?:a|td)>',
    re.DOTALL | re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class DiscoveredSource:
    """One public web source used as a procurement candidate seed."""

    url: str
    title: str
    snippet: str
    page_text: str


class LiveResearchClient(Protocol):
    async def search(self, query: str, *, limit: int = 8) -> tuple[SearchHit, ...]: ...

    async def fetch_text(self, url: str, *, maximum_bytes: int = 400_000) -> UntrustedContent: ...


class AgentReachResearchClient:
    """Shell out to Agent-Reach backends already installed on the machine."""

    def __init__(
        self,
        *,
        mcporter_bin: str = "mcporter",
        timeout_seconds: float = 45.0,
    ) -> None:
        self._mcporter_bin = mcporter_bin
        self._timeout_seconds = timeout_seconds

    async def search(self, query: str, *, limit: int = 8) -> tuple[SearchHit, ...]:
        try:
            raw = await asyncio.to_thread(self._mcporter_exa_search, query, limit)
            hits = _parse_exa_markdown(raw, limit=limit)
            if hits:
                return hits
        except (OSError, subprocess.SubprocessError, ValueError, TimeoutError):
            pass
        raw = await asyncio.to_thread(self._duckduckgo_html_search, query, limit)
        return _parse_duckduckgo_html(raw, limit=limit)

    async def fetch_text(self, url: str, *, maximum_bytes: int = 400_000) -> UntrustedContent:
        body = await asyncio.to_thread(self._jina_fetch, url, maximum_bytes)
        return UntrustedContent.from_body(
            url=url,
            body=body,
            media_type="text/markdown; charset=utf-8",
        )

    def _mcporter_exa_search(self, query: str, limit: int) -> str:
        # Agent Reach zero-config path: Exa via mcporter (free, no API key).
        selector = f"exa.web_search_exa(query: {json.dumps(query)}, numResults: {int(limit)})"
        completed = subprocess.run(
            [self._mcporter_bin, "call", selector],
            check=False,
            capture_output=True,
            text=True,
            timeout=self._timeout_seconds,
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "mcporter failed").strip()
            raise RuntimeError(detail[:500])
        return completed.stdout

    def _duckduckgo_html_search(self, query: str, limit: int) -> str:
        url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
        request = Request(
            url,
            headers={"User-Agent": _USER_AGENT, "Accept": "text/html"},
            method="GET",
        )
        with urlopen(request, timeout=self._timeout_seconds) as response:
            return response.read()[:500_000].decode("utf-8", errors="replace")

    def _jina_fetch(self, url: str, maximum_bytes: int) -> bytes:
        # Agent Reach zero-config page reader.
        reader_url = f"https://r.jina.ai/{url}"
        request = Request(
            reader_url,
            headers={"User-Agent": _USER_AGENT, "Accept": "text/plain"},
            method="GET",
        )
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                return response.read()[:maximum_bytes]
        except HTTPError as error:
            raise RuntimeError(f"Jina Reader rejected {url}: HTTP {error.code}") from error
        except URLError as error:
            raise RuntimeError(f"Jina Reader could not reach {url}") from error


class FakeResearchClient:
    """Deterministic offline research used by tests and CI."""

    def __init__(self, sources: tuple[DiscoveredSource, ...] | None = None) -> None:
        self._sources = sources or (
            DiscoveredSource(
                url="https://supplier-1.example.test/catalog/pump-a",
                title="Northstar Supply 316L sanitary transfer pump",
                snippet="Available sanitary pump. Lead time 24 days. Unit price USD 760.",
                page_text=(
                    "Northstar Supply\nOffering: 316L sanitary transfer pump\n"
                    "Available: yes\nLead time: 24 days\nUnit price: USD 760\n"
                ),
            ),
            DiscoveredSource(
                url="https://supplier-2.example.test/catalog/pump-b",
                title="Blue River Supply transfer pump option",
                snippet="Available. Lead time 29 days. Unit price USD 840.",
                page_text=(
                    "Blue River Supply\nOffering: transfer pump option\n"
                    "Available: yes\nLead time: 29 days\nUnit price: USD 840\n"
                ),
            ),
            DiscoveredSource(
                url="https://supplier-3.example.test/catalog/pump-c",
                title="Cedar Works Supply sanitary pump",
                snippet="Available. Lead time 42 days. Unit price USD 690.",
                page_text=(
                    "Cedar Works Supply\nOffering: sanitary pump\n"
                    "Available: yes\nLead time: 42 days\nUnit price: USD 690\n"
                ),
            ),
        )

    async def search(self, query: str, *, limit: int = 8) -> tuple[SearchHit, ...]:
        del query
        hits: list[SearchHit] = []
        for source in self._sources[:limit]:
            hits.append(
                SearchHit(
                    url=source.url,  # type: ignore[arg-type]
                    title=TaintedText(
                        value=source.title,
                        taint=frozenset({TaintLabel.REMOTE_CONTENT}),
                        source_urls=(source.url,),  # type: ignore[arg-type]
                    ),
                    snippet=TaintedText(
                        value=source.snippet,
                        taint=frozenset({TaintLabel.REMOTE_CONTENT}),
                        source_urls=(source.url,),  # type: ignore[arg-type]
                    ),
                )
            )
        return tuple(hits)

    async def fetch_text(self, url: str, *, maximum_bytes: int = 400_000) -> UntrustedContent:
        del maximum_bytes
        for source in self._sources:
            if source.url == url:
                return UntrustedContent.from_body(
                    url=url,
                    body=source.page_text.encode("utf-8"),
                    media_type="text/plain; charset=utf-8",
                )
        raise KeyError(f"unknown fake research url: {url}")


def _parse_exa_markdown(raw: str, *, limit: int) -> tuple[SearchHit, ...]:
    titles = _TITLE_RE.findall(raw)
    urls = _URL_RE.findall(raw)
    highlights = _HIGHLIGHT_BLOCK_RE.findall(raw)
    hits: list[SearchHit] = []
    for index, url in enumerate(urls[:limit]):
        title = titles[index].strip() if index < len(titles) else url
        snippet = (
            re.sub(r"\s+", " ", highlights[index]).strip()[:400]
            if index < len(highlights)
            else title
        )
        if not _is_public_http_url(url):
            continue
        hits.append(
            SearchHit(
                url=url,  # type: ignore[arg-type]
                title=TaintedText(
                    value=title[:500],
                    taint=frozenset({TaintLabel.REMOTE_CONTENT}),
                    source_urls=(url,),  # type: ignore[arg-type]
                ),
                snippet=TaintedText(
                    value=snippet[:500] or title[:500],
                    taint=frozenset({TaintLabel.REMOTE_CONTENT}),
                    source_urls=(url,),  # type: ignore[arg-type]
                ),
            )
        )
    return tuple(hits)


def _parse_duckduckgo_html(raw: str, *, limit: int) -> tuple[SearchHit, ...]:
    hits: list[SearchHit] = []
    for match in _DDG_RESULT_RE.finditer(raw):
        if len(hits) >= limit:
            break
        url = unquote(match.group(1))
        title = re.sub(r"<[^>]+>", "", unescape(match.group(2))).strip()
        snippet = re.sub(r"<[^>]+>", "", unescape(match.group(3))).strip()
        if not _is_public_http_url(url) or not title:
            continue
        hits.append(
            SearchHit(
                url=url,  # type: ignore[arg-type]
                title=TaintedText(
                    value=title[:500],
                    taint=frozenset({TaintLabel.REMOTE_CONTENT}),
                    source_urls=(url,),  # type: ignore[arg-type]
                ),
                snippet=TaintedText(
                    value=(snippet or title)[:500],
                    taint=frozenset({TaintLabel.REMOTE_CONTENT}),
                    source_urls=(url,),  # type: ignore[arg-type]
                ),
            )
        )
    return tuple(hits)


def _is_public_http_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return False
    host = (parsed.hostname or "").lower()
    if not host or host in {"localhost"} or host.endswith(".local"):
        return False
    return not (host.startswith("127.") or host.startswith("10.") or host.startswith("192.168."))


async def discover_sources(
    client: LiveResearchClient,
    *,
    item_name: str,
    description: str,
    limit: int = 5,
) -> tuple[DiscoveredSource, ...]:
    """Search the public web and read top result pages into source records."""

    query = f"{item_name} {description} supplier buy".strip()
    hits = await client.search(query, limit=limit)
    sources: list[DiscoveredSource] = []
    for hit in hits:
        url = str(hit.url)
        try:
            content = await client.fetch_text(url)
            page_text = content.body.decode("utf-8", errors="replace")
        except Exception:
            page_text = hit.snippet.value
        sources.append(
            DiscoveredSource(
                url=url,
                title=hit.title.value,
                snippet=hit.snippet.value,
                page_text=page_text[:50_000],
            )
        )
    if not sources:
        raise RuntimeError(
            "live research returned no usable public sources; "
            "check `agent-reach doctor` / mcporter Exa and network access"
        )
    return tuple(sources)
