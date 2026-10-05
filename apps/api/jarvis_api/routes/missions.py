from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from jarvis_api.missions import (
    Mission,
    MissionCreate,
    MissionPatch,
    MissionStore,
    RecordConflictError,
    RecordNotFoundError,
)
from jarvis_api.projects import ProjectNotFoundError

router = APIRouter(prefix="/missions", tags=["missions"])


def get_missions(request: Request) -> MissionStore:
    return request.app.state.missions


MissionDependency = Annotated[MissionStore, Depends(get_missions)]


def validate_project(request: Request, project_id: str | None) -> None:
    if project_id is not None:
        try:
            request.app.state.mission_projects.get(project_id)
        except ProjectNotFoundError as error:
            raise HTTPException(404, "Project not found") from error


@router.post("", response_model=Mission, status_code=201)
def create(body: MissionCreate, request: Request, store: MissionDependency) -> Mission:
    validate_project(request, body.project_id)
    return store.create(body)


@router.get("", response_model=list[Mission])
def list_missions(
    store: MissionDependency,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=2**63 - 1)] = 0,
) -> list[Mission]:
    return store.list(limit, offset)


@router.get("/{mission_id}", response_model=Mission)
def get(mission_id: UUID, store: MissionDependency) -> Mission:
    try:
        return store.get(mission_id)
    except RecordNotFoundError as error:
        raise HTTPException(404, "Mission not found") from error


@router.patch("/{mission_id}", response_model=Mission)
def patch(
    mission_id: UUID,
    body: MissionPatch,
    request: Request,
    store: MissionDependency,
) -> Mission:
    validate_project(request, body.project_id)
    try:
        return store.update(mission_id, body)
    except RecordNotFoundError as error:
        raise HTTPException(404, "Mission not found") from error
    except RecordConflictError as error:
        raise HTTPException(409, str(error)) from error
