from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from jarvis_api.assistants import get_assistant
from jarvis_api.config import get_settings
from jarvis_api.database import create_database_engine
from jarvis_api.ollama import OllamaService, OllamaUnavailableError
from jarvis_api.orchestration import AssistantOrchestrator
from jarvis_api.projects import ProjectNotFoundError, ProjectService
from jarvis_api.schemas import (
    ChatRequest,
    ChatResponse,
    HealthResponse,
    ProjectResponse,
    ProjectsResponse,
)
from jarvis_api.tools import ToolRegistry

VERSION = "0.3.0"
settings = get_settings()
engine = create_database_engine(settings.database_url)
ollama_service = OllamaService(settings.ollama_base_url, settings.ollama_model)
project_service = ProjectService(settings.projects_root)


def get_ollama_service() -> OllamaService:
    return ollama_service


def get_project_service() -> ProjectService:
    return project_service


OllamaDependency = Annotated[OllamaService, Depends(get_ollama_service)]
ProjectDependency = Annotated[ProjectService, Depends(get_project_service)]


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    yield
    engine.dispose()


app = FastAPI(title="JARVIS API", version=VERSION, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.get("/health", response_model=HealthResponse, tags=["system"])
async def health(service: OllamaDependency) -> HealthResponse:
    ollama_status = "online" if await service.is_available() else "offline"
    return HealthResponse(
        service="jarvis-api",
        version=VERSION,
        ollama=ollama_status,
        model=service.model,
    )


@app.post("/chat", response_model=ChatResponse, tags=["assistant"])
async def chat(
    request: ChatRequest,
    service: OllamaDependency,
    projects: ProjectDependency,
) -> ChatResponse:
    assistant = get_assistant("jarvis")
    try:
        orchestrator = AssistantOrchestrator(service, ToolRegistry(projects))
        response = await orchestrator.respond(request.message, assistant)
    except OllamaUnavailableError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Ollama is unavailable. Check that it is running and the model is installed.",
        ) from error
    return ChatResponse(response=response, model=service.model, assistant=assistant.identifier)


@app.get("/projects", response_model=ProjectsResponse, tags=["projects"])
def list_projects(projects: ProjectDependency) -> ProjectsResponse:
    discovered = projects.discover()
    return ProjectsResponse(
        projects=[ProjectResponse.model_validate(project.public_dict()) for project in discovered],
        recent_projects=[
            ProjectResponse.model_validate(project.public_dict()) for project in projects.recent(3)
        ],
        count=len(discovered),
        dirty_count=sum(project.is_dirty is True for project in discovered),
    )


@app.get("/projects/{project_id}", response_model=ProjectResponse, tags=["projects"])
def get_project(project_id: str, projects: ProjectDependency) -> ProjectResponse:
    try:
        project = projects.get(project_id)
    except ProjectNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Project not found"
        ) from error
    return ProjectResponse.model_validate(project.public_dict())
