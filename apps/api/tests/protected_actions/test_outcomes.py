import pytest

from sentinel_api.domain import ActionOutcomeState
from sentinel_api.protected_actions import InvalidOutcomeTransition, OutcomeMachine


def test_unknown_outcome_requires_reconciliation_before_retry() -> None:
    machine = (
        OutcomeMachine()
        .transition(ActionOutcomeState.PENDING_APPROVAL)
        .transition(ActionOutcomeState.APPROVED)
        .transition(ActionOutcomeState.DISPATCHING)
        .transition(ActionOutcomeState.OUTCOME_UNKNOWN)
    )

    with pytest.raises(InvalidOutcomeTransition):
        machine.transition(ActionOutcomeState.DISPATCHING)

    retriable = (
        machine.transition(ActionOutcomeState.RECONCILING)
        .transition(ActionOutcomeState.SAFE_TO_RETRY)
        .transition(ActionOutcomeState.DISPATCHING)
    )
    assert retriable.state is ActionOutcomeState.DISPATCHING
