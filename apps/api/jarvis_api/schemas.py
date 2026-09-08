from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    service: str
    version: str
    ollama: Literal["online", "offline"]
    model: str


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    conversation_id: UUID

    @field_validator("message")
    @classmethod
    def message_must_contain_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("message must contain text")
        return value


class ChatResponse(BaseModel):
    response: str
    model: str
    assistant: Literal["jarvis"] = "jarvis"
    conversation_id: UUID


class RunCreateRequest(ChatRequest):
    model_config = ConfigDict(extra="forbid")


class RunCancelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    conversation_id: UUID


class RunResponse(BaseModel):
    run_id: UUID
    conversation_id: UUID
    state: Literal[
        "QUEUED",
        "RUNNING",
        "WAITING_FOR_TOOL",
        "CANCELLING",
        "COMPLETED",
        "FAILED",
        "CANCELLED",
        "TIMED_OUT",
    ]
    created_at: str
    started_at: str | None
    completed_at: str | None


class ConversationResponse(BaseModel):
    conversation_id: UUID
    expires_in_seconds: int
    max_turns: int
    max_characters: int


class ProjectResponse(BaseModel):
    id: str
    name: str
    is_git_repository: bool
    branch: str | None
    is_dirty: bool | None
    latest_commit_message: str | None
    latest_commit_timestamp: str | None
    technologies: list[str]


class ProjectsResponse(BaseModel):
    projects: list[ProjectResponse]
    recent_projects: list[ProjectResponse]
    count: int
    dirty_count: int


class MemoryCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope: Literal["user", "project"]
    project_id: str | None = Field(
        default=None, min_length=16, max_length=16, pattern=r"^[a-f0-9]+$"
    )
    content: str = Field(min_length=1, max_length=4000)

    @field_validator("content")
    @classmethod
    def memory_must_contain_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("content must contain text")
        return value

    @model_validator(mode="after")
    def scope_matches_project(self) -> "MemoryCreateRequest":
        if self.scope == "project" and self.project_id is None:
            raise ValueError("project memory requires project_id")
        if self.scope == "user" and self.project_id is not None:
            raise ValueError("user memory cannot include project_id")
        return self


class MemoryUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: str = Field(min_length=1, max_length=4000)

    @field_validator("content")
    @classmethod
    def memory_must_contain_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("content must contain text")
        return value


class MemoryResponse(BaseModel):
    id: UUID
    scope: Literal["user", "project"]
    project_id: str | None
    project_name: str | None = None
    content: str
    created_at: str
    updated_at: str


class MemoryListResponse(BaseModel):
    memories: list[MemoryResponse]
    max_user_entries: int
    max_project_entries: int
    max_characters: int
    max_injected_characters: int
