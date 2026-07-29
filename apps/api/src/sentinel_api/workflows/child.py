"""Genuine isolated child workflow for one procurement work item."""

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

with workflow.unsafe.imports_passed_through():
    from .activities import EXECUTE_WORK_ACTIVITY
    from .failures import classify_activity_failure, is_cancelled_activity
    from .models import (
        ChildResult,
        ChildResultStatus,
        ChildWorkflowInput,
        WorkExecution,
    )


@workflow.defn(name="sentinel.procurement.child")
class ProcurementChildWorkflow:
    """Execute an isolated assignment and always return a structured result."""

    @workflow.run
    async def run(self, request: ChildWorkflowInput) -> ChildResult:
        execution = request.execution
        retry = execution.work_item.retry
        try:
            output = await workflow.execute_activity(
                EXECUTE_WORK_ACTIVITY,
                execution,
                result_type=WorkExecution,
                start_to_close_timeout=timedelta(seconds=execution.work_item.timeout_seconds),
                retry_policy=RetryPolicy(
                    maximum_attempts=retry.maximum_attempts,
                    initial_interval=timedelta(seconds=retry.initial_interval_seconds),
                    maximum_interval=timedelta(seconds=retry.maximum_interval_seconds),
                    non_retryable_error_types=[
                        classification
                        for classification in (
                            "auth_required",
                            "policy_denied",
                            "input_required",
                            "source_changed",
                            "conflict",
                            "tool_bug",
                            "outcome_unknown",
                            "terminal",
                        )
                    ],
                ),
            )
        except ActivityError as error:
            if is_cancelled_activity(error):
                return ChildResult(
                    work_item_id=execution.work_item.work_item_id,
                    child_run_id=execution.child_run_id,
                    status=ChildResultStatus.CANCELLED,
                    attempt=execution.attempt,
                    summary="Child activity cooperatively cancelled",
                )
            failure = classify_activity_failure(error)
            return ChildResult(
                work_item_id=execution.work_item.work_item_id,
                child_run_id=execution.child_run_id,
                status=ChildResultStatus.FAILED,
                attempt=execution.attempt,
                summary=failure.message,
                failure=failure,
            )
        return ChildResult(
            work_item_id=execution.work_item.work_item_id,
            child_run_id=execution.child_run_id,
            status=ChildResultStatus.COMPLETED,
            attempt=execution.attempt,
            summary=output.summary,
            output_ref=output.output_ref,
            products=output.products,
        )
