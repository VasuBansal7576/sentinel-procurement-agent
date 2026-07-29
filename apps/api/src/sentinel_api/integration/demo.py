"""Explicit, fail-closed controls for a deterministic human-operated demo."""

from __future__ import annotations

from dataclasses import dataclass

from sentinel_api.config import Settings


@dataclass(frozen=True, slots=True)
class DemoProfile:
    """Credential-free pacing and one first-attempt failure injection."""

    enabled: bool = False
    step_delay_seconds: float = 0
    failure_step: str | None = None

    @classmethod
    def from_settings(cls, settings: Settings) -> DemoProfile:
        return cls(
            enabled=settings.demo_mode,
            step_delay_seconds=settings.demo_step_delay_ms / 1_000,
            failure_step=settings.demo_failure_step,
        )

    @property
    def disclosure(self) -> str:
        if not self.enabled:
            return (
                "Deterministic local research and fake email. "
                "Approval records permission only; it never sends."
            )
        failure = (
            f" First run stops at {self.failure_step} for targeted recovery."
            if self.failure_step
            else ""
        )
        return (
            "DEMO MODE: deterministic local research, fake email, and visible pacing."
            f"{failure} Approval records permission only; it never sends."
        )
