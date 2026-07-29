"""Deterministic external-effect outcome state machine."""

from dataclasses import dataclass

from sentinel_api.domain import ActionOutcomeState


class InvalidOutcomeTransition(RuntimeError):
    """Raised when retry semantics would hide or duplicate an external effect."""


_ALLOWED: dict[ActionOutcomeState, frozenset[ActionOutcomeState]] = {
    ActionOutcomeState.PREPARED: frozenset({ActionOutcomeState.PENDING_APPROVAL}),
    ActionOutcomeState.PENDING_APPROVAL: frozenset({ActionOutcomeState.APPROVED}),
    ActionOutcomeState.APPROVED: frozenset({ActionOutcomeState.DISPATCHING}),
    ActionOutcomeState.DISPATCHING: frozenset(
        {
            ActionOutcomeState.CONFIRMED,
            ActionOutcomeState.FAILED_BEFORE_EFFECT,
            ActionOutcomeState.OUTCOME_UNKNOWN,
        }
    ),
    ActionOutcomeState.OUTCOME_UNKNOWN: frozenset({ActionOutcomeState.RECONCILING}),
    ActionOutcomeState.RECONCILING: frozenset(
        {
            ActionOutcomeState.CONFIRMED,
            ActionOutcomeState.SAFE_TO_RETRY,
            ActionOutcomeState.NEEDS_OPERATOR,
        }
    ),
    ActionOutcomeState.SAFE_TO_RETRY: frozenset({ActionOutcomeState.DISPATCHING}),
    ActionOutcomeState.FAILED_BEFORE_EFFECT: frozenset({ActionOutcomeState.DISPATCHING}),
    ActionOutcomeState.CONFIRMED: frozenset(),
    ActionOutcomeState.NEEDS_OPERATOR: frozenset(),
}


@dataclass(frozen=True, slots=True)
class OutcomeMachine:
    state: ActionOutcomeState = ActionOutcomeState.PREPARED

    def transition(self, next_state: ActionOutcomeState) -> "OutcomeMachine":
        if next_state not in _ALLOWED[self.state]:
            raise InvalidOutcomeTransition(
                f"cannot transition external action from {self.state} to {next_state}"
            )
        return OutcomeMachine(state=next_state)
