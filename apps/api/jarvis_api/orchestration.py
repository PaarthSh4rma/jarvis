import re
from dataclasses import dataclass

from jarvis_api.assistants import Assistant
from jarvis_api.conversations import ConversationTurn
from jarvis_api.ollama import OllamaService
from jarvis_api.projects import ProjectNotFoundError
from jarvis_api.tools import ToolCall, ToolError, ToolRegistry

EXPLICIT_OPEN_PATTERN = re.compile(
    r"^\s*(?:please\s+)?(?:open|launch|show)\b.*\b(?:vs\s*code|vscode|finder)\b",
    re.IGNORECASE,
)
ORDINAL_PATTERN = re.compile(r"\b(first|1st|second|2nd|third|3rd)\s+(?:one|project)\b", re.I)
REFERENCE_PATTERN = re.compile(r"\b(it|its|that project|the project)\b", re.I)
LIST_PROJECTS_PATTERN = re.compile(
    r"\b(?:what|which|list|show)\b.*\bprojects?\b", re.IGNORECASE
)
ORDINAL_INDEX = {"first": 0, "1st": 0, "second": 1, "2nd": 1, "third": 2, "3rd": 2}


@dataclass(frozen=True)
class AssistantResult:
    text: str
    tool_observation: dict[str, object] | None = None


@dataclass(frozen=True)
class ReferenceResolution:
    project_id: str | None = None
    project_name: str | None = None
    ambiguous: bool = False


class AssistantOrchestrator:
    def __init__(self, ollama: OllamaService, tools: ToolRegistry) -> None:
        self.ollama = ollama
        self.tools = tools

    async def respond(
        self,
        message: str,
        assistant: Assistant,
        history: tuple[ConversationTurn, ...] = (),
    ) -> AssistantResult:
        reference = self._resolve_reference(message, history)
        if reference.ambiguous:
            return AssistantResult(
                "Which project do you mean? I do not have one unambiguous project reference."
            )

        routing_context = self.tools.routing_context()
        if reference.project_id is None:
            reference = self._resolve_named_project(message, routing_context)
        if reference.project_id:
            routing_context["resolved_reference"] = {
                "project_id": reference.project_id,
                "project_name": reference.project_name,
                "instruction": "Use this exact project ID for the current reference.",
            }
        call = self._deterministic_tool(message, reference)
        if call is None:
            call = await self.ollama.route_tool(message, assistant, routing_context, history)
        if call is None:
            return AssistantResult(await self.ollama.chat(message, assistant, history))
        if reference.project_id and not self._call_matches_reference(call, reference.project_id):
            return AssistantResult(
                "I could not safely match that reference to the requested project. Which project "
                "do you mean?"
            )

        allow_external_actions = self._allows_external_action(message, call, reference)
        try:
            result = self.tools.execute(call, allow_external_actions=allow_external_actions)
        except ToolError:
            return AssistantResult(
                "I could not validate that project operation, so nothing was executed."
            )
        response = self._format_grounded_response(message, call.name, result)
        return AssistantResult(response, self._compact_observation(call.name, result))

    @staticmethod
    def _deterministic_tool(
        message: str, reference: ReferenceResolution
    ) -> ToolCall | None:
        """Route trusted project references and unambiguous list intent without model variance."""
        if reference.project_id:
            normalised = message.casefold().replace(" ", "")
            if EXPLICIT_OPEN_PATTERN.search(message):
                target = "finder" if "finder" in normalised else "vscode"
                return ToolCall(
                    name="open_project",
                    arguments={"project_id": reference.project_id, "target": target},
                )
            return ToolCall(
                name="get_project_status",
                arguments={"project_id": reference.project_id},
            )
        if LIST_PROJECTS_PATTERN.search(message):
            return ToolCall(name="list_projects", arguments={})
        return None

    def _resolve_reference(
        self, message: str, history: tuple[ConversationTurn, ...]
    ) -> ReferenceResolution:
        ordinal = ORDINAL_PATTERN.search(message)
        has_reference = ordinal is not None or REFERENCE_PATTERN.search(message) is not None
        if not has_reference:
            return ReferenceResolution()

        candidates = self._latest_candidates(history)
        if ordinal:
            index = ORDINAL_INDEX[ordinal.group(1).casefold()]
            if index >= len(candidates):
                return ReferenceResolution(ambiguous=True)
            project = candidates[index]
            return ReferenceResolution(str(project["id"]), str(project["name"]))
        if len(candidates) != 1:
            return ReferenceResolution(ambiguous=True)
        project = candidates[0]
        return ReferenceResolution(str(project["id"]), str(project["name"]))

    @staticmethod
    def _latest_candidates(history: tuple[ConversationTurn, ...]) -> list[dict[str, object]]:
        for turn in reversed(history):
            observation = turn.tool_observation or {}
            result = observation.get("result")
            if not isinstance(result, dict):
                continue
            project = result.get("project")
            if isinstance(project, dict) and project.get("id") and project.get("name"):
                return [project]
            projects = result.get("projects")
            if isinstance(projects, list):
                candidates = [
                    item
                    for item in projects
                    if isinstance(item, dict) and item.get("id") and item.get("name")
                ]
                if re.search(r"\b(dirty|uncommitted)\b", turn.user, re.I):
                    candidates = [item for item in candidates if item.get("is_dirty") is True]
                return candidates
        return []

    @staticmethod
    def _resolve_named_project(
        message: str, routing_context: dict[str, object]
    ) -> ReferenceResolution:
        projects = routing_context.get("projects")
        if not isinstance(projects, list):
            return ReferenceResolution()
        normalised_message = message.casefold()
        matches = [
            item
            for item in projects
            if isinstance(item, dict)
            and isinstance(item.get("id"), str)
            and isinstance(item.get("name"), str)
            and re.search(
                rf"(?<![\w-]){re.escape(str(item['name']).casefold())}(?![\w-])",
                normalised_message,
            )
        ]
        if len(matches) != 1:
            return ReferenceResolution()
        project = matches[0]
        return ReferenceResolution(str(project["id"]), str(project["name"]))

    @staticmethod
    def _call_matches_reference(call: ToolCall, project_id: str) -> bool:
        if call.name not in {"get_project_status", "open_project"}:
            return False
        return call.arguments.get("project_id") == project_id

    def _allows_external_action(
        self, message: str, call: ToolCall, reference: ReferenceResolution
    ) -> bool:
        if call.name != "open_project" or not EXPLICIT_OPEN_PATTERN.search(message):
            return False
        project_id = call.arguments.get("project_id")
        target = call.arguments.get("target")
        if not isinstance(project_id, str) or target not in {"vscode", "finder"}:
            return False
        normalised = message.casefold().replace(" ", "")
        target_is_named = target == "finder" and "finder" in normalised
        target_is_named = target_is_named or (
            target == "vscode" and ("vscode" in normalised or "visualstudiocode" in normalised)
        )
        if reference.project_id:
            return target_is_named and project_id == reference.project_id
        try:
            project = self.tools.projects.get(project_id)
        except ProjectNotFoundError:
            return False
        return target_is_named and project.name.casefold().replace(" ", "") in normalised

    @staticmethod
    def _compact_observation(tool_name: str, result: dict[str, object]) -> dict[str, object]:
        compact = dict(result)
        projects = compact.get("projects")
        if isinstance(projects, list) and len(projects) > 10:
            compact["projects"] = projects[:10]
            compact["truncated"] = True
            compact["project_count"] = len(projects)
        return {"tool": tool_name, "result": compact}

    @staticmethod
    def _format_grounded_response(
        message: str, tool_name: str, result: dict[str, object]
    ) -> str:
        """Render approved observations without asking the model to reinterpret fields."""
        if tool_name == "list_projects":
            raw_projects = result.get("projects")
            projects = raw_projects if isinstance(raw_projects, list) else []
            if re.search(r"\b(dirty|uncommitted)\b", message, re.I):
                projects = [
                    item
                    for item in projects
                    if isinstance(item, dict) and item.get("is_dirty") is True
                ]
                if not projects:
                    return "No projects have uncommitted changes."
                names = ", ".join(str(item["name"]) for item in projects)
                return f"Projects with uncommitted changes: {names}."
            names = [str(item["name"]) for item in projects if isinstance(item, dict)]
            if not names:
                return "No projects were discovered."
            return "Projects: " + "; ".join(
                f"{index}. {name}" for index, name in enumerate(names, start=1)
            ) + "."

        if tool_name == "get_project_status":
            project = result.get("project")
            if not isinstance(project, dict):
                return "The project status result was incomplete."
            name = str(project.get("name", "That project"))
            if re.search(r"\bbranch\b", message, re.I):
                branch = project.get("branch")
                return (
                    f"{name} is on branch {branch}."
                    if branch is not None
                    else f"{name} has no reported branch."
                )
            if re.search(r"\b(updated|update|commit(?:ted)?)\b", message, re.I):
                timestamp = project.get("latest_commit_timestamp")
                return (
                    f"{name} was last updated at {timestamp}."
                    if timestamp is not None
                    else f"No last-updated timestamp was reported for {name}."
                )
            if re.search(r"\b(technology|technologies|stack|language)\b", message, re.I):
                technologies = project.get("technologies")
                if isinstance(technologies, list) and technologies:
                    return f"{name} uses {', '.join(str(item) for item in technologies)}."
                return f"No technologies were reported for {name}."
            dirty = project.get("is_dirty")
            if dirty is True:
                return f"{name} has uncommitted changes."
            if dirty is False:
                return f"{name} has no uncommitted changes."
            return f"The working-tree state for {name} was not reported."

        if tool_name == "open_project":
            opened = result.get("opened")
            target = result.get("target")
            return f"Opened {opened} in {'VS Code' if target == 'vscode' else 'Finder'}."

        return "The approved tool completed, but returned no displayable result."
