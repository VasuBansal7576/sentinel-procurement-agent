"""Client-side entry point enforcing one parent workflow per procurement run."""

from uuid import UUID

from temporalio.client import Client, WorkflowHandle
from temporalio.common import WorkflowIDReusePolicy

from .models import ProcurementRunInput, ProcurementRunResult
from .parent import ProcurementParentWorkflow


def parent_workflow_id(run_id: str) -> str:
    """Return the canonical, globally stable Temporal workflow ID for a run."""

    return f"sentinel-procurement/{UUID(run_id)}"


async def start_procurement_run(
    client: Client,
    request: ProcurementRunInput,
    *,
    task_queue: str,
) -> WorkflowHandle[ProcurementParentWorkflow, ProcurementRunResult]:
    """Start the run's sole parent and reject replacement after it closes."""

    return await client.start_workflow(
        ProcurementParentWorkflow.run,
        request,
        id=parent_workflow_id(request.run_id),
        task_queue=task_queue,
        id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
    )
