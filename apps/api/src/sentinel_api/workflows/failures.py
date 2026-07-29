"""Stable failure classification shared by child workflows and tests."""

from temporalio.exceptions import (
    ActivityError,
    ApplicationError,
    CancelledError,
    FailureError,
)

from .models import FailureClass, FailureRecord

_CLASSIFICATIONS = {classification.value: classification for classification in FailureClass}
_RETRYABLE = {FailureClass.TRANSIENT, FailureClass.RATE_LIMITED}


def is_cancelled_activity(error: ActivityError) -> bool:
    """Return whether an activity failure chain represents cooperative cancellation."""

    cause: BaseException | None = error.cause
    while isinstance(cause, FailureError):
        if isinstance(cause, CancelledError):
            return True
        cause = cause.cause
    return False


def classify_activity_failure(error: ActivityError) -> FailureRecord:
    """Collapse a Temporal failure chain into Sentinel's explicit taxonomy."""

    cause: BaseException | None = error.cause
    while isinstance(cause, FailureError) and cause.cause is not None:
        if isinstance(cause, ApplicationError):
            break
        cause = cause.cause

    error_type: str | None = None
    if isinstance(cause, ApplicationError):
        error_type = cause.type
    classification = _CLASSIFICATIONS.get(
        (error_type or "").lower(),
        FailureClass.TOOL_BUG,
    )
    message = str(cause or error)
    return FailureRecord(
        classification=classification,
        message=message,
        retryable=classification in _RETRYABLE,
        error_type=error_type,
    )
