import asyncio
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from jarvis_api.assistants import Assistant
from jarvis_api.conversations import ConversationTurn
from jarvis_api.memory import MemoryEntry, MemoryStore
from jarvis_api.ollama import OllamaService
from jarvis_api.projects import ProjectNotFoundError
from jarvis_api.tools import ToolCall, ToolError, ToolRegistry

EXPLICIT_OPEN_PATTERN = re.compile(
    r"^\s*(?:please\s+)?(?:open|launch|show)\b.*\b(?:vs\s*code|vscode|finder)\b",
    re.IGNORECASE,
)
OPEN_INTENT_PATTERN = re.compile(
    r"^\s*(?:please\s+)?(?:open|launch)\b", re.IGNORECASE
)
OPEN_DESTINATION_FOLLOWUP_PATTERN = re.compile(
    r"^\s*(?:in\s+)?(?:vs\s*code|vscode|finder)[.!?]*\s*$", re.IGNORECASE
)
ORDINAL_PATTERN = re.compile(r"\b(first|1st|second|2nd|third|3rd)\s+(?:one|project)\b", re.I)
REFERENCE_PATTERN = re.compile(r"\b(it|its|that project|this project|the project)\b", re.I)
LIST_PROJECTS_PATTERN = re.compile(
    r"\b(?:what|which|list|show)\b.*\bprojects?\b", re.IGNORECASE
)
REMEMBER_PATTERN = re.compile(
    r"\b(?:remember\s+(?:that|this\s+exact\s+note\s*:|this\s*:?)|"
    r"save\s+this(?:\s*:)?|keep\s+this\s+in\s+mind(?:\s*:)?)[\s]+(.+)$",
    re.IGNORECASE,
)
PROJECT_MEMORY_INTENT_PATTERN = re.compile(r"^\s*for\s+.+?,\s*remember\b", re.I)
DESCRIBED_PROJECT_PATTERN = re.compile(
    r"^\s*for\s+(?:the\s+)?(.+?)\s+project\s*,", re.IGNORECASE
)
FORGET_PATTERN = re.compile(
    r"^\s*(?:please\s+)?(?:forget|remove)\s+(?:that\s+|the\s+)?(?:memory\s+)?(?:about\s+)?(.+?)(?:\s+memory)?[.!?]*\s*$",
    re.IGNORECASE,
)
LIST_MEMORY_PATTERN = re.compile(r"\b(?:what|list|show)\b.*\bremember|\bmemories\b", re.I)
LIVE_PROJECT_FIELD_PATTERN = re.compile(
    r"\b(branch|updated|update|commit(?:ted)?|technology|technologies|stack|language|dirty|uncommitted|status)\b",
    re.I,
)
PROJECT_TOOL_CANDIDATE_PATTERN = re.compile(
    r"\b(?:project|projects|repo|repos|repository|repositories)\b",
    re.IGNORECASE,
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
    def __init__(
        self, ollama: OllamaService, tools: ToolRegistry, memories: MemoryStore | None = None
    ) -> None:
        self.ollama = ollama
        self.tools = tools
        self.memories = memories

    async def respond(
        self,
        message: str,
        assistant: Assistant,
        history: tuple[ConversationTurn, ...] = (),
        *,
        delta_handler: Callable[[str], Awaitable[None]] | None = None,
        progress_handler: Callable[[str, str, str], None] | None = None,
        tool_timeout_seconds: float | None = None,
        raise_tool_errors: bool = False,
    ) -> AssistantResult:
        routing_context = self.tools.routing_context()
        reference = self._resolve_explicit_project(message, routing_context)
        if reference.project_id is None and not reference.ambiguous:
            reference = self._resolve_reference(message, history)
        if (
            reference.project_id is None
            and not reference.ambiguous
            and OPEN_DESTINATION_FOLLOWUP_PATTERN.match(message)
        ):
            reference = self._resolve_latest_unique_project(history)
        if reference.ambiguous:
            return AssistantResult(
                "Which project do you mean? I do not have one unambiguous project reference."
            )
        if reference.project_id is None:
            reference = self._resolve_named_project(message, routing_context)
        if reference.project_id:
            routing_context["resolved_reference"] = {
                "project_id": reference.project_id,
                "project_name": reference.project_name,
                "instruction": "Use this exact project ID for the current reference.",
            }
        memory_result = self._handle_memory_intent(message, reference)
        if memory_result is not None:
            return memory_result
        memory_context = self._memory_context(reference.project_id)
        call = self._deterministic_tool(message, reference)
        if call is None and OPEN_INTENT_PATTERN.search(message):
            if reference.project_id:
                return AssistantResult(
                    f"Where should I open {reference.project_name}—VS Code or Finder?",
                    self._project_reference_observation(reference),
                )
            return AssistantResult("Which project should I open, and in VS Code or Finder?")
        if call is None and self._is_project_tool_candidate(message, reference):
            call = await self.ollama.route_tool(message, assistant, routing_context, history)
        if call is None:
            return AssistantResult(
                await self._chat(
                    message, assistant, history, memory_context, delta_handler
                )
            )
        if reference.project_id and not self._call_matches_reference(call, reference.project_id):
            return AssistantResult(
                "I could not safely match that reference to the requested project. Which project "
                "do you mean?"
            )

        allow_external_actions = self._allows_external_action(message, call, reference)
        try:
            if progress_handler:
                description = self._tool_description(call.name, reference.project_name)
                progress_handler("tool.requested", call.name, description)
                progress_handler("tool.started", call.name, description)
            if tool_timeout_seconds is None:
                result = self.tools.execute(call, allow_external_actions=allow_external_actions)
            else:
                result = await asyncio.wait_for(
                    asyncio.to_thread(
                        self.tools.execute,
                        call,
                        allow_external_actions=allow_external_actions,
                    ),
                    timeout=tool_timeout_seconds,
                )
            if progress_handler:
                progress_handler("tool.completed", call.name, "Tool completed")
        except (ToolError, TimeoutError):
            if progress_handler:
                progress_handler("tool.failed", call.name, "Tool failed safely")
            if raise_tool_errors:
                raise
            return AssistantResult(
                "I could not validate that project operation, so nothing was executed."
            )
        response = self._format_grounded_response(message, call.name, result)
        return AssistantResult(response, self._compact_observation(call.name, result))

    @staticmethod
    def _is_project_tool_candidate(
        message: str, reference: ReferenceResolution
    ) -> bool:
        return bool(
            PROJECT_TOOL_CANDIDATE_PATTERN.search(message)
            or (reference.project_id and LIVE_PROJECT_FIELD_PATTERN.search(message))
        )

    @staticmethod
    def _project_reference_observation(
        reference: ReferenceResolution,
    ) -> dict[str, object]:
        return {
            "tool": "resolve_project",
            "result": {
                "project": {
                    "id": reference.project_id,
                    "name": reference.project_name,
                }
            },
        }

    @staticmethod
    def _deterministic_tool(
        message: str, reference: ReferenceResolution
    ) -> ToolCall | None:
        """Route trusted project references and unambiguous list intent without model variance."""
        if reference.project_id:
            normalised = message.casefold().replace(" ", "")
            if EXPLICIT_OPEN_PATTERN.search(message) or OPEN_DESTINATION_FOLLOWUP_PATTERN.match(
                message
            ):
                target = "finder" if "finder" in normalised else "vscode"
                return ToolCall(
                    name="open_project",
                    arguments={"project_id": reference.project_id, "target": target},
                )
            if LIVE_PROJECT_FIELD_PATTERN.search(message):
                return ToolCall(
                    name="get_project_status",
                    arguments={"project_id": reference.project_id},
                )
        if LIST_PROJECTS_PATTERN.search(message):
            return ToolCall(name="list_projects", arguments={})
        return None

    def _memory_context(self, project_id: str | None) -> tuple[MemoryEntry, ...]:
        return self.memories.context(project_id) if self.memories is not None else ()

    async def _chat(
        self,
        message: str,
        assistant: Assistant,
        history: tuple[ConversationTurn, ...],
        memory_context: tuple[MemoryEntry, ...],
        delta_handler: Callable[[str], Awaitable[None]] | None = None,
    ) -> str:
        if delta_handler is not None:
            chunks: list[str] = []
            async for chunk in self.ollama.chat_stream(
                message, assistant, history, memories=memory_context
            ):
                chunks.append(chunk)
                await delta_handler(chunk)
            return "".join(chunks)
        if memory_context:
            return await self.ollama.chat(
                message, assistant, history, memories=memory_context
            )
        return await self.ollama.chat(message, assistant, history)

    @staticmethod
    def _tool_description(tool_name: str, project_name: str | None) -> str:
        subject = project_name or "local projects"
        descriptions = {
            "get_project_status": f"Inspecting {subject} state",
            "open_project": f"Opening {subject}",
            "list_projects": "Inspecting local project index",
        }
        return descriptions.get(tool_name, "Running approved local tool")

    def _handle_memory_intent(
        self, message: str, reference: ReferenceResolution
    ) -> AssistantResult | None:
        if self.memories is None:
            return None
        remember = REMEMBER_PATTERN.search(message)
        if remember:
            if PROJECT_MEMORY_INTENT_PATTERN.search(message) and not reference.project_id:
                return AssistantResult(
                    "Which project do you mean? I will not guess where to store that memory."
                )
            content = remember.group(1).strip().rstrip(".!?")
            scope = "project" if reference.project_id else "user"
            entry = self.memories.add(scope, content, reference.project_id)
            label = reference.project_name if scope == "project" else "user"
            return AssistantResult(
                f"Remembered for {label}: {entry.content}.",
                {
                    "tool": "memory_add",
                    "result": {"scope": scope, "saved": True},
                },
            )

        forget = FORGET_PATTERN.match(message)
        if forget:
            candidates = list(self._memory_context(reference.project_id))
            if reference.project_id:
                candidates = [entry for entry in candidates if entry.scope == "project"]
            else:
                candidates = [entry for entry in candidates if entry.scope == "user"]
            terms = self._memory_search_terms(forget.group(1), reference.project_name)
            matches = [
                entry
                for entry in candidates
                if terms and all(term in entry.content.casefold() for term in terms)
            ]
            if len(matches) > 1:
                return AssistantResult(
                    "Which memory do you mean? More than one saved memory matches that request."
                )
            if not matches:
                return AssistantResult("I could not find a matching saved memory.")
            self.memories.delete(matches[0].id)
            return AssistantResult(
                f"Forgot: {matches[0].content}.",
                {"tool": "memory_delete", "result": {"scope": matches[0].scope}},
            )

        if LIST_MEMORY_PATTERN.search(message):
            entries = self._memory_context(reference.project_id)
            if reference.project_id:
                entries = tuple(entry for entry in entries if entry.scope == "project")
            if not entries:
                return AssistantResult("No matching memories are saved.")
            return AssistantResult(
                "Saved memories: "
                + "; ".join(f"{index}. {entry.content}" for index, entry in enumerate(entries, 1))
                + "."
            )
        return None

    @staticmethod
    def _memory_search_terms(value: str, project_name: str | None) -> list[str]:
        ignored = {"the", "that", "memory", "about", "old", "project", "s"}
        if project_name:
            ignored.update(re.findall(r"[a-z0-9]+", project_name.casefold()))
        return [
            term
            for term in re.findall(r"[a-z0-9]+", value.casefold())
            if term not in ignored
        ]

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

    @classmethod
    def _resolve_explicit_project(
        cls, message: str, routing_context: dict[str, object]
    ) -> ReferenceResolution:
        named = cls._resolve_named_project(message, routing_context)
        if named.project_id:
            return named
        descriptor = DESCRIBED_PROJECT_PATTERN.search(message)
        if descriptor is None or descriptor.group(1).casefold() in {"this", "the"}:
            return ReferenceResolution()
        terms = re.findall(r"[a-z0-9]+", descriptor.group(1).casefold())
        projects = routing_context.get("projects")
        if not terms or not isinstance(projects, list):
            return ReferenceResolution(ambiguous=True)
        matches = [
            project
            for project in projects
            if isinstance(project, dict)
            and isinstance(project.get("id"), str)
            and isinstance(project.get("name"), str)
            and all(term in str(project["name"]).casefold() for term in terms)
        ]
        if len(matches) != 1:
            return ReferenceResolution(ambiguous=True)
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
        if call.name != "open_project" or not (
            EXPLICIT_OPEN_PATTERN.search(message)
            or OPEN_DESTINATION_FOLLOWUP_PATTERN.match(message)
        ):
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

    def _resolve_latest_unique_project(
        self, history: tuple[ConversationTurn, ...]
    ) -> ReferenceResolution:
        candidates = self._latest_candidates(history)
        if len(candidates) != 1:
            return ReferenceResolution(ambiguous=True)
        project = candidates[0]
        return ReferenceResolution(str(project["id"]), str(project["name"]))

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
