from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Literal
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
from jarvis_api.memory import MemoryEntry, MemoryLimitError, MemoryNotFoundError, MemoryStore
from jarvis_api.ollama import OllamaService, OllamaUnavailableError
from jarvis_api.orchestration import AssistantOrchestrator
from jarvis_api.projects import ProjectNotFoundError, ProjectService
from jarvis_api.schemas import (
    ChatRequest,
    ChatResponse,
    ConversationResponse,
    HealthResponse,
    MemoryCreateRequest,
    MemoryListResponse,
    MemoryResponse,
    MemoryUpdateRequest,
    ProjectResponse,
    ProjectsResponse,
)
from jarvis_api.tools import ToolRegistry

VERSION = "0.5.0"
settings = get_settings()
engine = create_database_engine(settings.database_url)
ollama_service = OllamaService(settings.ollama_base_url, settings.ollama_model)
project_service = ProjectService(settings.projects_root)
conversation_store = ConversationStore(
    ttl_seconds=settings.conversation_ttl_seconds,
    max_turns=settings.conversation_max_turns,
    max_characters=settings.conversation_max_characters,
)
memory_store = MemoryStore(
    engine,
    max_user_entries=settings.memory_max_user_entries,
    max_project_entries=settings.memory_max_project_entries,
    max_characters=settings.memory_max_characters,
    max_injected_characters=settings.memory_max_injected_characters,
)


def get_ollama_service() -> OllamaService:
    return ollama_service


def get_project_service() -> ProjectService:
    return project_service


def get_conversation_store() -> ConversationStore:
    return conversation_store


def get_memory_store() -> MemoryStore:
    return memory_store


OllamaDependency = Annotated[OllamaService, Depends(get_ollama_service)]
ProjectDependency = Annotated[ProjectService, Depends(get_project_service)]
ConversationDependency = Annotated[ConversationStore, Depends(get_conversation_store)]
MemoryDependency = Annotated[MemoryStore, Depends(get_memory_store)]


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    memory_store.initialize()
    yield
    engine.dispose()


app = FastAPI(title="JARVIS API", version=VERSION, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
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
    memories: MemoryDependency,
) -> ChatResponse:
    assistant = get_assistant("jarvis")
    try:
        session = conversations.get(request.conversation_id)
        orchestrator = AssistantOrchestrator(service, ToolRegistry(projects), memories)
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
    except MemoryLimitError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
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


def _memory_response(
    entry: MemoryEntry, project_name: str | None = None
) -> MemoryResponse:
    return MemoryResponse(
        id=UUID(entry.id),
        scope=entry.scope,
        project_id=entry.project_id,
        project_name=project_name,
        content=entry.content,
        created_at=entry.created_at.isoformat(),
        updated_at=entry.updated_at.isoformat(),
    )


@app.get("/memory", response_model=MemoryListResponse, tags=["memory"])
def list_memory(
    memories: MemoryDependency,
    projects: ProjectDependency,
    scope: Literal["user", "project"] | None = None,
    project_id: str | None = None,
) -> MemoryListResponse:
    if project_id is not None:
        try:
            projects.get(project_id)
        except ProjectNotFoundError as error:
            raise HTTPException(status_code=404, detail="Project not found") from error
        scope = "project"
    entries = memories.list(scope=scope, project_id=project_id)
    project_names = {project.id: project.name for project in projects.discover()} if any(
        entry.project_id for entry in entries
    ) else {}
    return MemoryListResponse(
        memories=[
            _memory_response(
                entry,
                project_names.get(entry.project_id, "Unavailable project")
                if entry.project_id
                else None,
            )
            for entry in entries
        ],
        max_user_entries=memories.max_user_entries,
        max_project_entries=memories.max_project_entries,
        max_characters=memories.max_characters,
        max_injected_characters=memories.max_injected_characters,
    )


@app.post(
    "/memory",
    response_model=MemoryResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["memory"],
)
def add_memory(
    request: MemoryCreateRequest,
    memories: MemoryDependency,
    projects: ProjectDependency,
) -> MemoryResponse:
    project_name = None
    if request.project_id is not None:
        try:
            project_name = projects.get(request.project_id).name
        except ProjectNotFoundError as error:
            raise HTTPException(status_code=404, detail="Project not found") from error
    try:
        entry = memories.add(request.scope, request.content, request.project_id)
    except MemoryLimitError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return _memory_response(entry, project_name)


@app.patch("/memory/{memory_id}", response_model=MemoryResponse, tags=["memory"])
def update_memory(
    memory_id: UUID,
    request: MemoryUpdateRequest,
    memories: MemoryDependency,
    projects: ProjectDependency,
) -> MemoryResponse:
    try:
        entry = memories.update(str(memory_id), request.content)
    except MemoryNotFoundError as error:
        raise HTTPException(status_code=404, detail="Memory not found") from error
    except MemoryLimitError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    project_name = None
    if entry.project_id:
        try:
            project_name = projects.get(entry.project_id).name
        except ProjectNotFoundError:
            project_name = "Unavailable project"
    return _memory_response(entry, project_name)


@app.delete(
    "/memory/{memory_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["memory"]
)
def delete_memory(memory_id: UUID, memories: MemoryDependency) -> None:
    try:
        memories.delete(str(memory_id))
    except MemoryNotFoundError as error:
        raise HTTPException(status_code=404, detail="Memory not found") from error
