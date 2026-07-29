"""Provider interfaces and credential-free search/fetch boundaries."""

from __future__ import annotations

from typing import Protocol

from sentinel_api.research.models import (
    FetchRequest,
    RawFetchResponse,
    SearchHit,
    SearchQuery,
    UntrustedContent,
)
from sentinel_api.research.security import ResearchCapability, ResearchGrant, UrlPolicy


class SearchProvider(Protocol):
    async def search(self, query: SearchQuery) -> tuple[SearchHit, ...]:
        """Return public search results without privileged provider state."""


class FetchTransport(Protocol):
    async def fetch(
        self,
        request: FetchRequest,
        url_policy: UrlPolicy,
    ) -> RawFetchResponse:
        """Apply policy before DNS/connect and every redirect; never attach credentials."""


class ResearchSearch:
    def __init__(self, provider: SearchProvider) -> None:
        self._provider = provider

    async def search(self, grant: ResearchGrant, query: SearchQuery) -> tuple[SearchHit, ...]:
        grant.require(ResearchCapability.SEARCH)
        effective_domains = grant.allowed_domains
        if query.allowed_domains:
            if not query.allowed_domains <= grant.allowed_domains:
                raise PermissionError("search query cannot expand the actor domain grant")
            effective_domains = query.allowed_domains
        hits = await self._provider.search(
            query.model_copy(update={"allowed_domains": effective_domains})
        )
        policy = UrlPolicy(effective_domains)
        for hit in hits:
            policy.validate(str(hit.url))
        return hits


class ResearchFetch:
    def __init__(self, transport: FetchTransport) -> None:
        self._transport = transport

    async def fetch(self, grant: ResearchGrant, request: FetchRequest) -> UntrustedContent:
        grant.require(ResearchCapability.FETCH)
        policy = UrlPolicy(grant.allowed_domains)
        policy.validate(str(request.url))
        response = await self._transport.fetch(request, policy)
        policy.validate(str(response.final_url))
        if response.requested_url != request.url:
            raise ValueError("transport response does not match the requested URL")
        if len(response.body) > request.maximum_bytes:
            raise ValueError("fetch response exceeds the requested byte limit")
        if request.accepted_media_types and response.media_type not in request.accepted_media_types:
            raise ValueError("fetch response media type is not accepted")
        return UntrustedContent.from_body(
            url=str(response.final_url),
            body=response.body,
            media_type=response.media_type,
            retrieved_at=response.retrieved_at,
        )
