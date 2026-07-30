"""HTTP commands and projections for the real operator workbench gateway."""

from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status

from sentinel_api.application.walking_skeleton import CreateRunRequest
from sentinel_api.integration.models import (
    AutonomyCommandRequest,
    CommandRequest,
    MessageCommandRequest,
    ProposalDecisionRequest,
    ProposalEditRequest,
    RedirectCommandRequest,
    RetryRequest,
)
from sentinel_api.integration.service import IntegrationService

router = APIRouter(prefix="/operator", tags=["operator"])


def service_from_app(request: Request) -> IntegrationService:
    service = getattr(request.app.state, "integration_service", None)
    if not isinstance(service, IntegrationService):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="integration runtime is not configured",
        )
    return service


@router.get("/sessions")
async def list_sessions(request: Request) -> list[dict[str, object]]:
    return await service_from_app(request).list_sessions()


@router.post("/runs", status_code=status.HTTP_201_CREATED)
async def create_run(
    body: CreateRunRequest,
    request: Request,
) -> dict[str, object]:
    return await service_from_app(request).create_run(body)


@router.get("/runs/{run_id}")
async def get_run(run_id: UUID, request: Request) -> dict[str, object]:
    try:
        return await service_from_app(request).get_run(run_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Run not found") from error


@router.get("/runs/{run_id}/work-tree")
async def get_work_tree(run_id: UUID, request: Request) -> list[dict[str, object]]:
    try:
        return await service_from_app(request).get_work_tree(run_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Run not found") from error


@router.post("/runs/{run_id}/controls/{action}")
async def control_run(
    run_id: UUID,
    action: str,
    body: CommandRequest,
    request: Request,
) -> dict[str, object]:
    try:
        return await service_from_app(request).control(run_id, action, body)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Run not found") from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post("/runs/{run_id}/autonomy")
async def set_autonomy(
    run_id: UUID,
    body: AutonomyCommandRequest,
    request: Request,
) -> dict[str, object]:
    try:
        return await service_from_app(request).set_autonomy(run_id, body)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Run not found") from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post("/runs/{run_id}/messages")
async def queue_message(
    run_id: UUID,
    body: MessageCommandRequest,
    request: Request,
) -> dict[str, object]:
    try:
        return await service_from_app(request).queue_message(run_id, body)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Run not found") from error


@router.post("/runs/{run_id}/redirect")
async def redirect(
    run_id: UUID,
    body: RedirectCommandRequest,
    request: Request,
) -> dict[str, object]:
    try:
        return await service_from_app(request).redirect(run_id, body)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Run not found") from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post("/runs/{run_id}/work/{work_id}/retry")
async def retry_work(
    run_id: UUID,
    work_id: UUID,
    body: RetryRequest,
    request: Request,
) -> dict[str, object]:
    try:
        return await service_from_app(request).retry_work(
            run_id,
            work_id,
            body.command_id,
        )
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.put("/runs/{run_id}/proposal")
async def edit_proposal(
    run_id: UUID,
    body: ProposalEditRequest,
    request: Request,
) -> dict[str, object]:
    try:
        return await service_from_app(request).edit_proposal(run_id, body)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Proposal not found") from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post("/runs/{run_id}/proposal/decision")
async def decide_proposal(
    run_id: UUID,
    body: ProposalDecisionRequest,
    request: Request,
) -> dict[str, object]:
    try:
        return await service_from_app(request).decide_proposal(run_id, body)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Proposal not found") from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post("/runs/{run_id}/proposal/execute")
async def execute_approved_email(
    run_id: UUID,
    request: Request,
) -> dict[str, object]:
    try:
        return await service_from_app(request).execute_approved_email(run_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
