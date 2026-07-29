"""Strict models for public research data and untrusted-content taint."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from uuid import UUID

from pydantic import Field, HttpUrl, model_validator

from sentinel_api.domain import ContractModel, utc_now


class TaintLabel(StrEnum):
    """Labels that survive every research-data boundary."""

    REMOTE_CONTENT = "remote_content"
    USER_SUPPLIED_CONTENT = "user_supplied_content"
    AGENT_HELPER_OUTPUT = "agent_helper_output"


class TaintedText(ContractModel):
    """Text that must never be interpreted as trusted control-plane input."""

    value: str = Field(max_length=100_000)
    taint: frozenset[TaintLabel] = Field(min_length=1)
    source_urls: tuple[HttpUrl, ...] = ()


class UntrustedContent(ContractModel):
    """A bounded remote response with a verified content digest."""

    url: HttpUrl
    body: bytes = Field(max_length=10_000_000)
    media_type: str = Field(min_length=3, max_length=160)
    retrieved_at: datetime = Field(default_factory=utc_now)
    content_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    taint: frozenset[TaintLabel] = frozenset({TaintLabel.REMOTE_CONTENT})

    @model_validator(mode="after")
    def verify_digest_and_taint(self) -> UntrustedContent:
        if sha256(self.body).hexdigest() != self.content_sha256:
            raise ValueError("content digest does not match response body")
        if TaintLabel.REMOTE_CONTENT not in self.taint:
            raise ValueError("remote content must retain remote-content taint")
        return self

    @classmethod
    def from_body(
        cls,
        *,
        url: str,
        body: bytes,
        media_type: str,
        retrieved_at: datetime | None = None,
        additional_taint: frozenset[TaintLabel] = frozenset(),
    ) -> UntrustedContent:
        """Create a response while binding its digest and mandatory taint."""

        return cls.model_validate(
            {
                "url": url,
                "body": body,
                "media_type": media_type,
                "retrieved_at": retrieved_at or utc_now(),
                "content_sha256": sha256(body).hexdigest(),
                "taint": frozenset({TaintLabel.REMOTE_CONTENT}) | additional_taint,
            }
        )


class SearchQuery(ContractModel):
    """Provider-neutral public-web search request."""

    text: str = Field(min_length=2, max_length=500)
    limit: int = Field(default=10, ge=1, le=50)
    allowed_domains: frozenset[str] = frozenset()


class SearchHit(ContractModel):
    """A search result whose provider-authored fields remain tainted."""

    url: HttpUrl
    title: TaintedText
    snippet: TaintedText

    @model_validator(mode="after")
    def require_remote_taint(self) -> SearchHit:
        for field in (self.title, self.snippet):
            if TaintLabel.REMOTE_CONTENT not in field.taint:
                raise ValueError("search result text must retain remote-content taint")
        return self


class FetchRequest(ContractModel):
    """Credential-free HTTP retrieval request."""

    url: HttpUrl
    maximum_bytes: int = Field(default=5_000_000, ge=1, le=10_000_000)
    accepted_media_types: frozenset[str] = frozenset()


class RawFetchResponse(ContractModel):
    """Transport response validated by the research fetch boundary."""

    requested_url: HttpUrl
    final_url: HttpUrl
    body: bytes = Field(max_length=10_000_000)
    media_type: str = Field(min_length=3, max_length=160)
    retrieved_at: datetime = Field(default_factory=utc_now)


class SessionHandle(ContractModel):
    """Opaque browser-session handle bound to one run and actor."""

    token: UUID
    run_id: UUID
    actor_id: UUID
