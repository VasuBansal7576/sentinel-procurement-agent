"""Typed tool namespace, capability, risk, and retry metadata."""

from enum import StrEnum
from typing import Self

from pydantic import Field, model_validator

from sentinel_api.domain.common import ContractModel


class ToolNamespace(StrEnum):
    SEARCH = "search"
    FETCH = "fetch"
    BROWSER = "browser"
    PROCUREMENT = "procurement"
    EVIDENCE = "evidence"
    ARTIFACT = "artifact"
    POLICY = "policy"
    EMAIL = "email"


class RiskClass(StrEnum):
    READ = "read"
    INTERNAL_WRITE = "internal_write"
    EXTERNAL_SEND = "external_send"
    SPEND = "spend"
    DESTRUCTIVE = "destructive"


class RetryPolicy(ContractModel):
    max_attempts: int = Field(default=3, ge=1, le=10)
    initial_delay_seconds: float = Field(default=0.5, ge=0, le=300)
    maximum_delay_seconds: float = Field(default=30, ge=0, le=3600)
    retry_on_unknown_outcome: bool = False

    @model_validator(mode="after")
    def validate_delays(self) -> Self:
        if self.maximum_delay_seconds < self.initial_delay_seconds:
            raise ValueError("maximum delay cannot be shorter than initial delay")
        return self


class ToolMetadata(ContractModel):
    namespace: ToolNamespace
    name: str = Field(pattern=r"^[a-z][a-z0-9_]{1,79}$")
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    risk_class: RiskClass
    allowed_actor_capabilities: frozenset[str] = Field(min_length=1)
    timeout_seconds: float = Field(gt=0, le=3600)
    retry_policy: RetryPolicy = Field(default_factory=RetryPolicy)
    idempotent: bool
    accepts_untrusted_data: bool
    protected_sink: bool

    @model_validator(mode="after")
    def validate_protected_risk(self) -> Self:
        protected_risks = {
            RiskClass.EXTERNAL_SEND,
            RiskClass.SPEND,
            RiskClass.DESTRUCTIVE,
        }
        if self.risk_class in protected_risks and not self.protected_sink:
            raise ValueError("effectful tools must be marked as protected sinks")
        if self.protected_sink and "research" in self.allowed_actor_capabilities:
            raise ValueError("research actors cannot receive protected sinks")
        return self
