from collections.abc import Mapping
from uuid import uuid4

import pytest

from sentinel_api.research import (
    BrowserBroker,
    BrowserPrimitive,
    FetchRequest,
    HelperManifest,
    HelperPatch,
    RawFetchResponse,
    ResearchCapability,
    ResearchFetch,
    ResearchGrant,
    ResearchSearch,
    SearchHit,
    SearchQuery,
    SessionHandle,
    TaintedText,
    TaintLabel,
    UntrustedContent,
    UrlPolicy,
)


def _grant(
    *,
    run_id: object | None = None,
    actor_id: object | None = None,
    domains: frozenset[str] = frozenset({"example.com"}),
    capabilities: frozenset[ResearchCapability] | None = None,
) -> ResearchGrant:
    return ResearchGrant(
        run_id=run_id or uuid4(),
        actor_id=actor_id or uuid4(),
        capabilities=capabilities
        or frozenset(
            {
                ResearchCapability.SEARCH,
                ResearchCapability.FETCH,
                ResearchCapability.BROWSER_READ,
                ResearchCapability.HELPER_EXECUTION,
            }
        ),
        allowed_domains=domains,
    )


class FakeSearchProvider:
    def __init__(self, result_url: str = "https://example.com/item") -> None:
        self.result_url = result_url
        self.last_query: SearchQuery | None = None

    async def search(self, query: SearchQuery) -> tuple[SearchHit, ...]:
        self.last_query = query
        taint = frozenset({TaintLabel.REMOTE_CONTENT})
        return (
            SearchHit(
                url=self.result_url,
                title=TaintedText(value="Product", taint=taint),
                snippet=TaintedText(value="Supplier result", taint=taint),
            ),
        )


class FakeFetchTransport:
    def __init__(
        self,
        *,
        final_url: str = "https://example.com/item",
        body: bytes = b"<p>Product</p>",
        media_type: str = "text/html",
    ) -> None:
        self.final_url = final_url
        self.body = body
        self.media_type = media_type

    async def fetch(
        self,
        request: FetchRequest,
        url_policy: UrlPolicy,
    ) -> RawFetchResponse:
        return RawFetchResponse(
            requested_url=request.url,
            final_url=self.final_url,
            body=self.body,
            media_type=self.media_type,
        )


class FakeBrowserBackend:
    def __init__(self) -> None:
        self.created: list[str] = []
        self.closed: list[str] = []
        self.navigations: list[tuple[str, str]] = []
        self.helper_contexts: list[str] = []

    async def create_context(self, url_policy: UrlPolicy) -> str:
        context_id = f"context-{len(self.created) + 1}"
        self.created.append(context_id)
        return context_id

    async def navigate(self, context_id: str, url: str) -> UntrustedContent:
        self.navigations.append((context_id, url))
        return UntrustedContent.from_body(
            url=url,
            body=b"<html>supplier page</html>",
            media_type="text/html",
        )

    async def run_helper(
        self,
        context_id: str,
        patch: HelperPatch,
        arguments: Mapping[str, str],
    ) -> UntrustedContent:
        self.helper_contexts.append(context_id)
        return UntrustedContent.from_body(
            url="https://example.com/item",
            body=f"{patch.manifest.name}:{arguments['selector']}".encode(),
            media_type="text/plain",
            additional_taint=frozenset({TaintLabel.AGENT_HELPER_OUTPUT}),
        )

    async def close_context(self, context_id: str) -> None:
        self.closed.append(context_id)


@pytest.mark.asyncio
async def test_search_narrows_domains_and_rejects_provider_escape() -> None:
    provider = FakeSearchProvider()
    search = ResearchSearch(provider)
    grant = _grant(domains=frozenset({"example.com", "example.org"}))

    hits = await search.search(
        grant,
        SearchQuery(text="product", allowed_domains=frozenset({"example.com"})),
    )

    assert hits[0].url.host == "example.com"
    assert provider.last_query is not None
    assert provider.last_query.allowed_domains == frozenset({"example.com"})

    with pytest.raises(PermissionError, match="cannot expand"):
        await search.search(
            grant,
            SearchQuery(text="product", allowed_domains=frozenset({"attacker.test"})),
        )

    provider.result_url = "https://attacker.test/injected"
    with pytest.raises(PermissionError, match="not allowed"):
        await search.search(
            grant,
            SearchQuery(text="product", allowed_domains=frozenset({"example.com"})),
        )


@pytest.mark.asyncio
async def test_fetch_revalidates_redirect_size_and_media_type() -> None:
    grant = _grant()
    valid = await ResearchFetch(FakeFetchTransport()).fetch(
        grant,
        FetchRequest(
            url="https://example.com/start",
            maximum_bytes=100,
            accepted_media_types=frozenset({"text/html"}),
        ),
    )
    assert TaintLabel.REMOTE_CONTENT in valid.taint

    with pytest.raises(PermissionError, match="not allowed"):
        await ResearchFetch(FakeFetchTransport(final_url="https://attacker.test/injection")).fetch(
            grant, FetchRequest(url="https://example.com/start")
        )

    with pytest.raises(ValueError, match="byte limit"):
        await ResearchFetch(FakeFetchTransport(body=b"too long")).fetch(
            grant,
            FetchRequest(url="https://example.com/start", maximum_bytes=2),
        )

    with pytest.raises(ValueError, match="media type"):
        await ResearchFetch(FakeFetchTransport(media_type="application/pdf")).fetch(
            grant,
            FetchRequest(
                url="https://example.com/start",
                accepted_media_types=frozenset({"text/html"}),
            ),
        )


@pytest.mark.asyncio
async def test_fetch_rejects_transport_request_substitution() -> None:
    class SubstitutingTransport(FakeFetchTransport):
        async def fetch(
            self,
            request: FetchRequest,
            url_policy: UrlPolicy,
        ) -> RawFetchResponse:
            return RawFetchResponse(
                requested_url="https://example.com/different",
                final_url="https://example.com/item",
                body=b"substituted",
                media_type="text/plain",
            )

    with pytest.raises(ValueError, match="does not match"):
        await ResearchFetch(SubstitutingTransport()).fetch(
            _grant(),
            FetchRequest(url="https://example.com/start"),
        )


@pytest.mark.asyncio
async def test_browser_sessions_are_distinct_and_actor_bound() -> None:
    backend = FakeBrowserBackend()
    broker = BrowserBroker(backend)
    run_id = uuid4()
    first_grant = _grant(run_id=run_id)
    second_grant = _grant(run_id=run_id)
    first = await broker.open_session(first_grant)
    second = await broker.open_session(second_grant)

    await broker.navigate(first_grant, first, "https://example.com/item")
    await broker.navigate(second_grant, second, "https://example.com/other")

    assert backend.created == ["context-1", "context-2"]
    assert backend.navigations == [
        ("context-1", "https://example.com/item"),
        ("context-2", "https://example.com/other"),
    ]

    with pytest.raises(PermissionError, match="different run or actor"):
        await broker.navigate(second_grant, first, "https://example.com/item")

    forged = SessionHandle(token=first.token, run_id=first.run_id, actor_id=uuid4())
    with pytest.raises(PermissionError, match="handle binding"):
        await broker.navigate(first_grant, forged, "https://example.com/item")

    await broker.close_session(first_grant, first)
    assert backend.closed == ["context-1"]
    with pytest.raises(PermissionError, match="unknown or closed"):
        await broker.navigate(first_grant, first, "https://example.com/item")


@pytest.mark.asyncio
async def test_browser_revalidates_backend_redirect_and_helper_binding() -> None:
    class RedirectingBackend(FakeBrowserBackend):
        async def navigate(self, context_id: str, url: str) -> UntrustedContent:
            return UntrustedContent.from_body(
                url="http://169.254.169.254/latest/meta-data",
                body=b"secret",
                media_type="text/plain",
            )

    grant = _grant()
    redirecting_broker = BrowserBroker(RedirectingBackend())
    handle = await redirecting_broker.open_session(grant)
    with pytest.raises(PermissionError):
        await redirecting_broker.navigate(grant, handle, "https://example.com/item")

    backend = FakeBrowserBackend()
    broker = BrowserBroker(backend)
    handle = await broker.open_session(grant)
    patch = HelperPatch.create(
        run_id=grant.run_id,
        actor_id=grant.actor_id,
        manifest=HelperManifest(
            name="extract_price",
            version="1.0.0",
            primitives=frozenset({BrowserPrimitive.READ_TEXT}),
            allowed_domains=frozenset({"example.com"}),
        ),
        source_code="return rpc.read_text(args['selector'])",
    )
    result = await broker.run_helper(grant, handle, patch, {"selector": ".price"})
    assert TaintLabel.AGENT_HELPER_OUTPUT in result.taint
    assert backend.helper_contexts == ["context-1"]

    other_actor_patch = HelperPatch.create(
        run_id=grant.run_id,
        actor_id=uuid4(),
        manifest=patch.manifest,
        source_code=patch.source_code,
    )
    with pytest.raises(PermissionError, match="not bound"):
        await broker.run_helper(grant, handle, other_actor_patch, {})

    overbroad_patch = HelperPatch.create(
        run_id=grant.run_id,
        actor_id=grant.actor_id,
        manifest=HelperManifest(
            name="leave_domain",
            version="1.0.0",
            primitives=frozenset({BrowserPrimitive.NAVIGATE}),
            allowed_domains=frozenset({"attacker.test"}),
        ),
        source_code="return rpc.navigate('https://attacker.test')",
    )
    with pytest.raises(PermissionError, match="domains exceed"):
        await broker.run_helper(grant, handle, overbroad_patch, {})


@pytest.mark.asyncio
async def test_browser_revalidates_helper_output_location() -> None:
    class RedirectingHelperBackend(FakeBrowserBackend):
        async def run_helper(
            self,
            context_id: str,
            patch: HelperPatch,
            arguments: Mapping[str, str],
        ) -> UntrustedContent:
            return UntrustedContent.from_body(
                url="https://attacker.test/exfiltrate",
                body=b"injected helper output",
                media_type="text/plain",
                additional_taint=frozenset({TaintLabel.AGENT_HELPER_OUTPUT}),
            )

    grant = _grant()
    broker = BrowserBroker(RedirectingHelperBackend())
    handle = await broker.open_session(grant)
    patch = HelperPatch.create(
        run_id=grant.run_id,
        actor_id=grant.actor_id,
        manifest=HelperManifest(
            name="extract_price",
            version="1.0.0",
            primitives=frozenset({BrowserPrimitive.READ_TEXT}),
            allowed_domains=frozenset({"example.com"}),
        ),
        source_code="return rpc.read_text('.price')",
    )

    with pytest.raises(PermissionError, match="not allowed"):
        await broker.run_helper(grant, handle, patch, {})


@pytest.mark.asyncio
async def test_missing_capability_denies_before_provider_or_browser_use() -> None:
    grant = _grant(capabilities=frozenset({ResearchCapability.SEARCH}))

    with pytest.raises(PermissionError, match="fetch"):
        await ResearchFetch(FakeFetchTransport()).fetch(
            grant,
            FetchRequest(url="https://example.com/item"),
        )

    backend = FakeBrowserBackend()
    with pytest.raises(PermissionError, match="browser_read"):
        await BrowserBroker(backend).open_session(grant)
    assert backend.created == []
