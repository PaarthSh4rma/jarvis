from typing import Annotated

from fastapi import APIRouter, Depends, Request

from jarvis_api.integrations.hermes import HermesAdapter, HermesStatus

router = APIRouter(prefix="/integrations/hermes", tags=["integrations"])


def get_hermes(request: Request) -> HermesAdapter:
    return request.app.state.hermes


HermesDependency = Annotated[HermesAdapter, Depends(get_hermes)]


@router.get("/health", response_model=HermesStatus)
async def health(hermes: HermesDependency) -> HermesStatus:
    return await hermes.health()


@router.get("/capabilities", response_model=HermesStatus)
async def capabilities(hermes: HermesDependency) -> HermesStatus:
    return await hermes.capabilities()
