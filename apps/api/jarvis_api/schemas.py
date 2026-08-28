from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


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
