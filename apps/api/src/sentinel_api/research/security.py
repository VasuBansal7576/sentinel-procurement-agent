"""Deterministic research capability, egress, and injection boundaries."""

from __future__ import annotations

import re
from enum import StrEnum
from ipaddress import ip_address
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from sentinel_api.domain import ContractModel, RiskClass, ToolMetadata
from sentinel_api.research.models import TaintedText, TaintLabel, UntrustedContent


class ResearchCapability(StrEnum):
    SEARCH = "search"
    FETCH = "fetch"
    BROWSER_READ = "browser_read"
    HELPER_EXECUTION = "helper_execution"


_DNS_NAME = re.compile(
    r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)*"
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$"
)


def normalize_allowed_domains(domains: frozenset[str]) -> frozenset[str]:
    """Normalize and validate exact/suffix DNS allowlist entries."""

    normalized = frozenset(domain.rstrip(".").lower() for domain in domains)
    if not normalized or any(_DNS_NAME.fullmatch(domain) is None for domain in normalized):
        raise ValueError("allowed domains must be valid bare DNS names")
    return normalized


class ResearchGrant(ContractModel):
    """Least-privilege grant for exactly one research actor."""

    run_id: UUID
    actor_id: UUID
    capabilities: frozenset[ResearchCapability] = Field(min_length=1)
    allowed_domains: frozenset[str] = Field(min_length=1)
    tools: tuple[ToolMetadata, ...] = ()
    credential_names: frozenset[str] = frozenset()

    @field_validator("allowed_domains")
    @classmethod
    def normalize_domains(cls, domains: frozenset[str]) -> frozenset[str]:
        return normalize_allowed_domains(domains)

    @model_validator(mode="after")
    def enforce_research_boundary(self) -> ResearchGrant:
        if self.credential_names:
            raise ValueError("research actors cannot receive credentials")
        for tool in self.tools:
            if tool.protected_sink or tool.risk_class is not RiskClass.READ:
                raise ValueError("research actors can receive read-only, non-protected tools only")
            if "research" not in tool.allowed_actor_capabilities:
                raise ValueError("research tool must explicitly allow the research capability")
        return self

    def require(self, capability: ResearchCapability) -> None:
        if capability not in self.capabilities:
            raise PermissionError(f"research capability not granted: {capability}")


class UrlPolicy:
    """Validate URL and resolved-address egress before every network hop."""

    def __init__(self, allowed_domains: frozenset[str]) -> None:
        self._allowed_domains = normalize_allowed_domains(allowed_domains)

    def validate(self, url: str) -> str:
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"}:
            raise PermissionError("research egress allows HTTP(S) only")
        if parsed.username is not None or parsed.password is not None:
            raise PermissionError("research URLs cannot contain credentials")
        hostname = parsed.hostname
        if hostname is None:
            raise PermissionError("research URL requires a hostname")
        normalized_host = hostname.rstrip(".").lower()
        if not self._domain_allowed(normalized_host):
            raise PermissionError(f"research domain is not allowed: {normalized_host}")
        self._reject_non_public_literal(normalized_host)
        return url

    def _domain_allowed(self, hostname: str) -> bool:
        return any(
            hostname == domain or hostname.endswith(f".{domain}")
            for domain in self._allowed_domains
        )

    @staticmethod
    def _reject_non_public_literal(hostname: str) -> None:
        if hostname == "localhost":
            raise PermissionError("local network targets are not allowed")
        try:
            ip_address(hostname)
        except ValueError:
            return
        UrlPolicy.validate_resolved_address(hostname)

    @staticmethod
    def validate_resolved_address(address: str) -> str:
        """Reject DNS answers and direct targets outside the public Internet."""

        if not ip_address(address).is_global:
            raise PermissionError("non-public network targets are not allowed")
        return address


class InjectionSignalKind(StrEnum):
    CONTROL_OVERRIDE = "control_override"
    SECRET_REQUEST = "secret_request"
    PROTECTED_ACTION_REQUEST = "protected_action_request"


class InjectionSignal(ContractModel):
    kind: InjectionSignalKind
    matched_phrase: str = Field(min_length=2, max_length=160)


_INJECTION_PHRASES: tuple[tuple[InjectionSignalKind, str], ...] = (
    (InjectionSignalKind.CONTROL_OVERRIDE, "ignore previous instructions"),
    (InjectionSignalKind.CONTROL_OVERRIDE, "ignore system message"),
    (InjectionSignalKind.SECRET_REQUEST, "reveal the secret"),
    (InjectionSignalKind.SECRET_REQUEST, "print environment variables"),
    (InjectionSignalKind.PROTECTED_ACTION_REQUEST, "send an email"),
    (InjectionSignalKind.PROTECTED_ACTION_REQUEST, "make a purchase"),
    (InjectionSignalKind.PROTECTED_ACTION_REQUEST, "call the protected tool"),
)


def scan_for_injection(content: UntrustedContent) -> tuple[InjectionSignal, ...]:
    """Produce telemetry without treating detection as an authorization boundary."""

    decoded = content.body.decode("utf-8", errors="replace").lower()
    return tuple(
        InjectionSignal(kind=kind, matched_phrase=phrase)
        for kind, phrase in _INJECTION_PHRASES
        if phrase in decoded
    )


def tainted_tool_result(*, value: str, source: UntrustedContent) -> TaintedText:
    """Preserve source taint when an adaptive helper returns extracted text."""

    return TaintedText(
        value=value,
        taint=source.taint | frozenset({TaintLabel.AGENT_HELPER_OUTPUT}),
        source_urls=(source.url,),
    )
