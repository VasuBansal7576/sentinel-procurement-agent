"""Digest-bound contracts for per-run adaptive browser helpers."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from typing import Protocol, Self
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from sentinel_api.domain import ContractModel, utc_now
from sentinel_api.research.security import normalize_allowed_domains


class BrowserPrimitive(StrEnum):
    NAVIGATE = "navigate"
    READ_TEXT = "read_text"
    READ_ATTRIBUTE = "read_attribute"
    CLICK = "click"
    FILL_NON_SECRET = "fill_non_secret"
    SCREENSHOT = "screenshot"


class HelperManifest(ContractModel):
    name: str = Field(pattern=r"^[a-z][a-z0-9_]{1,79}$")
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    primitives: frozenset[BrowserPrimitive] = Field(min_length=1)
    allowed_domains: frozenset[str] = Field(min_length=1)
    accepts_credentials: bool = False
    protected_tool_names: frozenset[str] = frozenset()

    @field_validator("allowed_domains")
    @classmethod
    def normalize_domains(cls, domains: frozenset[str]) -> frozenset[str]:
        return normalize_allowed_domains(domains)

    @model_validator(mode="after")
    def prevent_privilege_escalation(self) -> HelperManifest:
        if self.accepts_credentials:
            raise ValueError("adaptive helpers cannot accept credentials")
        if self.protected_tool_names:
            raise ValueError("adaptive helpers cannot receive protected tools")
        return self


class HelperPatch(ContractModel):
    run_id: UUID
    actor_id: UUID
    manifest: HelperManifest
    source_code: str = Field(min_length=1, max_length=200_000)
    content_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    created_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def verify_digest(self) -> Self:
        if sha256(self.source_code.encode()).hexdigest() != self.content_sha256:
            raise ValueError("helper digest does not match source")
        return self

    @classmethod
    def create(
        cls,
        *,
        run_id: UUID,
        actor_id: UUID,
        manifest: HelperManifest,
        source_code: str,
    ) -> HelperPatch:
        canonical_source = source_code.replace("\r\n", "\n").strip()
        return cls(
            run_id=run_id,
            actor_id=actor_id,
            manifest=manifest,
            source_code=canonical_source,
            content_sha256=sha256(canonical_source.encode()).hexdigest(),
        )


class HelperPatchStore(Protocol):
    async def retain(self, patch: HelperPatch) -> None:
        """Retain a patch as a run-scoped artifact; never promote it globally."""

    async def get(self, run_id: UUID, content_sha256: str) -> HelperPatch:
        """Load a retained patch by run and immutable content digest."""


class InMemoryHelperPatchStore:
    """Reference run-scoped helper store used by tests and local adapters."""

    def __init__(self) -> None:
        self._patches: dict[tuple[UUID, str], HelperPatch] = {}

    async def retain(self, patch: HelperPatch) -> None:
        key = (patch.run_id, patch.content_sha256)
        existing = self._patches.get(key)
        if existing is not None and existing != patch:
            raise ValueError("immutable helper digest already retained with different metadata")
        self._patches[key] = patch

    async def get(self, run_id: UUID, content_sha256: str) -> HelperPatch:
        try:
            return self._patches[(run_id, content_sha256)]
        except KeyError as error:
            raise KeyError("helper patch not found for run") from error
