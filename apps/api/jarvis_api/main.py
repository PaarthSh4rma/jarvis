from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from jarvis_api.assistants import get_assistant
from jarvis_api.config import get_settings
from jarvis_api.conversations import (
    ConversationExpiredError,
    ConversationNotFoundError,
    ConversationStore,
)
from jarvis_api.database import create_database_engine
from jarvis_api.ollama import OllamaService, OllamaUnavailableError
from jarvis_api.orchestration import AssistantOrchestrator
from jarvis_api.projects import ProjectNotFoundError, ProjectService
from jarvis_api.schemas import (
    ChatRequest,
    ChatResponse,
    ConversationResponse,
    HealthResponse,
    ProjectResponse,
    ProjectsResponse,
)
from jarvis_api.tools import ToolRegistry

VERSION = "0.4.0"
settings = get_settings()
engine = create_database_engine(settings.database_url)
ollama_service = OllamaService(settings.ollama_base_url, settings.ollama_model)
project_service = ProjectService(settings.projects_root)
conversation_store = ConversationStore(
    ttl_seconds=settings.conversation_ttl_seconds,
    max_turns=settings.conversation_max_turns,
    max_characters=settings.conversation_max_characters,
)


def get_ollama_service() -> OllamaService:
    return ollama_service


def get_project_service() -> ProjectService:
    return project_service


def get_conversation_store() -> ConversationStore:
    return conversation_store


OllamaDependency = Annotated[OllamaService, Depends(get_ollama_service)]
ProjectDependency = Annotated[ProjectService, Depends(get_project_service)]
ConversationDependency = Annotated[ConversationStore, Depends(get_conversation_store)]


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
    allow_methods=["GET", "POST", "DELETE"],
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
    conversations: ConversationDependency,
) -> ChatResponse:
    assistant = get_assistant("jarvis")
    try:
        session = conversations.get(request.conversation_id)
        orchestrator = AssistantOrchestrator(service, ToolRegistry(projects))
        result = await orchestrator.respond(request.message, assistant, tuple(session.turns))
        conversations.append(
            request.conversation_id,
            user=request.message,
            assistant=result.text,
            tool_observation=result.tool_observation,
        )
    except ConversationExpiredError as error:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Conversation expired. Start a new session.",
        ) from error
    except ConversationNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found. Start a new session.",
        ) from error
    except OllamaUnavailableError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Ollama is unavailable. Check that it is running and the model is installed.",
        ) from error
    return ChatResponse(
        response=result.text,
        model=service.model,
        assistant=assistant.identifier,
        conversation_id=request.conversation_id,
    )


@app.post(
    "/conversations",
    response_model=ConversationResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["conversations"],
)
def create_conversation(conversations: ConversationDependency) -> ConversationResponse:
    session = conversations.create()
    return ConversationResponse(
        conversation_id=session.id,
        expires_in_seconds=conversations.ttl_seconds,
        max_turns=conversations.max_turns,
        max_characters=conversations.max_characters,
    )


@app.delete(
    "/conversations/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["conversations"],
)
def delete_conversation(
    conversation_id: UUID, conversations: ConversationDependency
) -> None:
    try:
        conversations.delete(conversation_id)
    except ConversationExpiredError as error:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Conversation already expired.",
        ) from error
    except ConversationNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found.",
        ) from error


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
