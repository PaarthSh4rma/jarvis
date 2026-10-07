"""Future worker data contracts, deliberately without execution implementations."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field

from jarvis_api.missions import StrictModel

AgentKind = Literal["CODEX", "CLAUDE"]


class AgentTask(StrictModel):
    mission_id: UUID
    agent: AgentKind
    goal: str = Field(min_length=1, max_length=4000)
    context: str = Field(default="", max_length=8000)
    permission_scope: Literal["READ_ONLY", "WORKSPACE_EDIT"] = "READ_ONLY"


class AgentResult(StrictModel):
    status: Literal["COMPLETED", "FAILED", "CANCELLED"]
    summary: str = Field(min_length=1, max_length=4000)
    artifacts: list[Annotated[str, Field(min_length=1, max_length=500)]] = Field(
        default_factory=list, max_length=20
    )
    validation: list[Annotated[str, Field(min_length=1, max_length=1000)]] = Field(
        default_factory=list, max_length=20
    )
    external_id: str | None = Field(default=None, max_length=200)
