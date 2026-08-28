from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from jarvis_api.projects import ProjectNotFoundError, ProjectService


class ToolError(RuntimeError):
    pass


class UnknownToolError(ToolError):
    pass


class ToolArgumentError(ToolError):
    pass


class ExternalActionDeniedError(ToolError):
    pass


class StrictArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ListProjectsArguments(StrictArguments):
    pass


class ProjectStatusArguments(StrictArguments):
    project_id: str = Field(min_length=16, max_length=16, pattern=r"^[a-f0-9]+$")


class RecentActivityArguments(StrictArguments):
    limit: int = Field(default=5, ge=1, le=10)


class OpenProjectArguments(ProjectStatusArguments):
    target: Literal["vscode", "finder"]


class ToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=64)
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ToolDefinition:
    arguments_model: type[StrictArguments]
    description: str


TOOL_DEFINITIONS = {
    "list_projects": ToolDefinition(ListProjectsArguments, "List discovered projects and status."),
    "get_project_status": ToolDefinition(ProjectStatusArguments, "Get one project by opaque ID."),
    "get_recent_project_activity": ToolDefinition(RecentActivityArguments, "List recent projects."),
    "open_project": ToolDefinition(OpenProjectArguments, "Open a project in VS Code or Finder."),
}


class ToolRegistry:
    def __init__(self, projects: ProjectService) -> None:
        self.projects = projects

    def routing_context(self) -> dict[str, object]:
        return {
            "tools": {
                name: {
                    "description": definition.description,
                    "arguments": definition.arguments_model.model_json_schema(),
                }
                for name, definition in TOOL_DEFINITIONS.items()
            },
            "projects": [{"id": item.id, "name": item.name} for item in self.projects.discover()],
        }

    def execute(self, call: ToolCall, allow_external_actions: bool = False) -> dict[str, object]:
        definition = TOOL_DEFINITIONS.get(call.name)
        if definition is None:
            raise UnknownToolError(f"Unknown tool: {call.name}")
        try:
            arguments = definition.arguments_model.model_validate(call.arguments)
        except ValidationError as error:
            raise ToolArgumentError("Malformed tool arguments") from error

        try:
            if call.name == "list_projects":
                projects = self.projects.discover()
                return {"projects": [project.public_dict() for project in projects]}
            if call.name == "get_project_status":
                assert isinstance(arguments, ProjectStatusArguments)
                return {"project": self.projects.get(arguments.project_id).public_dict()}
            if call.name == "get_recent_project_activity":
                assert isinstance(arguments, RecentActivityArguments)
                projects = self.projects.recent(arguments.limit)
                return {"projects": [project.public_dict() for project in projects]}
            if call.name == "open_project":
                if not allow_external_actions:
                    raise ExternalActionDeniedError(
                        "Opening a project requires explicit user intent"
                    )
                assert isinstance(arguments, OpenProjectArguments)
                project = self.projects.get(arguments.project_id)
                self.projects.open_project(arguments.project_id, arguments.target)
                return {
                    "opened": project.name,
                    "target": arguments.target,
                    "project": project.public_dict(),
                }
        except ProjectNotFoundError as error:
            raise ToolArgumentError("Unknown project identifier") from error
        raise UnknownToolError(f"Unknown tool: {call.name}")
