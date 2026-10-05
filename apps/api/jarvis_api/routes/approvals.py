from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from jarvis_api.approvals import Approval, ApprovalResolve, ApprovalStore
from jarvis_api.missions import RecordConflictError, RecordNotFoundError

router = APIRouter(prefix="/approvals", tags=["approvals"])


def get_approvals(request: Request) -> ApprovalStore:
    return request.app.state.approvals


ApprovalDependency = Annotated[ApprovalStore, Depends(get_approvals)]


@router.get("", response_model=list[Approval])
def list_approvals(
    store: ApprovalDependency,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=2**63 - 1)] = 0,
    mission_id: UUID | None = None,
) -> list[Approval]:
    return store.list(limit, offset, mission_id)


@router.get("/{approval_id}", response_model=Approval)
def get(approval_id: UUID, store: ApprovalDependency) -> Approval:
    try:
        return store.get(approval_id)
    except RecordNotFoundError as error:
        raise HTTPException(404, "Approval not found") from error


@router.post("/{approval_id}/resolve", response_model=Approval)
def resolve(approval_id: UUID, body: ApprovalResolve, store: ApprovalDependency) -> Approval:
    try:
        return store.resolve(approval_id, body)
    except RecordNotFoundError as error:
        raise HTTPException(404, "Approval not found") from error
    except RecordConflictError as error:
        raise HTTPException(409, str(error)) from error
