"""Capability-limited browser broker with actor-isolated sessions."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID, uuid4

from sentinel_api.research.helpers import HelperPatch
from sentinel_api.research.models import SessionHandle, UntrustedContent
from sentinel_api.research.security import ResearchCapability, ResearchGrant, UrlPolicy


class BrowserBackend(Protocol):
    async def create_context(self, url_policy: UrlPolicy) -> str:
        """Create a fresh context and enforce policy on documents and subresources."""

    async def navigate(self, context_id: str, url: str) -> UntrustedContent:
        """Navigate inside one isolated context and return tainted page content."""

    async def run_helper(
        self,
        context_id: str,
        patch: HelperPatch,
        arguments: Mapping[str, str],
    ) -> UntrustedContent:
        """Run a helper behind browser-only RPC primitives."""

    async def close_context(self, context_id: str) -> None:
        """Destroy all cookies, storage, and page state for the context."""


@dataclass(frozen=True, slots=True)
class _Session:
    context_id: str
    run_id: UUID
    actor_id: UUID
    allowed_domains: frozenset[str]


class BrowserBroker:
    """Own browser contexts so research actors see opaque handles only."""

    def __init__(self, backend: BrowserBackend) -> None:
        self._backend = backend
        self._sessions: dict[UUID, _Session] = {}

    async def open_session(self, grant: ResearchGrant) -> SessionHandle:
        grant.require(ResearchCapability.BROWSER_READ)
        context_id = await self._backend.create_context(UrlPolicy(grant.allowed_domains))
        token = uuid4()
        self._sessions[token] = _Session(
            context_id=context_id,
            run_id=grant.run_id,
            actor_id=grant.actor_id,
            allowed_domains=grant.allowed_domains,
        )
        return SessionHandle(token=token, run_id=grant.run_id, actor_id=grant.actor_id)

    async def navigate(
        self,
        grant: ResearchGrant,
        handle: SessionHandle,
        url: str,
    ) -> UntrustedContent:
        grant.require(ResearchCapability.BROWSER_READ)
        session = self._authorize(grant, handle)
        UrlPolicy(session.allowed_domains).validate(url)
        content = await self._backend.navigate(session.context_id, url)
        UrlPolicy(session.allowed_domains).validate(str(content.url))
        return content

    async def run_helper(
        self,
        grant: ResearchGrant,
        handle: SessionHandle,
        patch: HelperPatch,
        arguments: Mapping[str, str],
    ) -> UntrustedContent:
        grant.require(ResearchCapability.BROWSER_READ)
        grant.require(ResearchCapability.HELPER_EXECUTION)
        session = self._authorize(grant, handle)
        if patch.run_id != session.run_id or patch.actor_id != session.actor_id:
            raise PermissionError("helper patch is not bound to this browser session")
        if not patch.manifest.allowed_domains <= session.allowed_domains:
            raise PermissionError("helper domains exceed the browser session grant")
        content = await self._backend.run_helper(session.context_id, patch, arguments)
        UrlPolicy(session.allowed_domains).validate(str(content.url))
        return content

    async def close_session(
        self,
        grant: ResearchGrant,
        handle: SessionHandle,
    ) -> None:
        grant.require(ResearchCapability.BROWSER_READ)
        session = self._authorize(grant, handle)
        del self._sessions[handle.token]
        await self._backend.close_context(session.context_id)

    def _authorize(self, grant: ResearchGrant, handle: SessionHandle) -> _Session:
        session = self._sessions.get(handle.token)
        if session is None:
            raise PermissionError("unknown or closed browser session")
        expected = (session.run_id, session.actor_id)
        if expected != (grant.run_id, grant.actor_id):
            raise PermissionError("browser session belongs to a different run or actor")
        if expected != (handle.run_id, handle.actor_id):
            raise PermissionError("browser session handle binding is invalid")
        return session
