import re

from jarvis_api.assistants import Assistant
from jarvis_api.ollama import OllamaService
from jarvis_api.projects import ProjectNotFoundError
from jarvis_api.tools import ToolError, ToolRegistry

EXPLICIT_OPEN_PATTERN = re.compile(
    r"^\s*(?:please\s+)?(?:open|launch|show)\b.*\b(?:vs\s*code|vscode|finder)\b",
    re.IGNORECASE,
)


class AssistantOrchestrator:
    def __init__(self, ollama: OllamaService, tools: ToolRegistry) -> None:
        self.ollama = ollama
        self.tools = tools

    async def respond(self, message: str, assistant: Assistant) -> str:
        call = await self.ollama.route_tool(message, assistant, self.tools.routing_context())
        if call is None:
            return await self.ollama.chat(message, assistant)

        allow_external_actions = self._allows_external_action(message, call.name, call.arguments)
        try:
            result = self.tools.execute(call, allow_external_actions=allow_external_actions)
        except ToolError:
            return "I could not validate that project operation, so nothing was executed."
        return await self.ollama.chat_grounded(message, assistant, call.name, result)

    def _allows_external_action(
        self, message: str, tool_name: str, arguments: dict[str, object]
    ) -> bool:
        if tool_name != "open_project" or not EXPLICIT_OPEN_PATTERN.search(message):
            return False
        project_id = arguments.get("project_id")
        target = arguments.get("target")
        if not isinstance(project_id, str) or target not in {"vscode", "finder"}:
            return False
        normalised = message.casefold().replace(" ", "")
        target_is_named = target == "finder" and "finder" in normalised
        target_is_named = target_is_named or (
            target == "vscode" and ("vscode" in normalised or "visualstudiocode" in normalised)
        )
        try:
            project = self.tools.projects.get(project_id)
        except ProjectNotFoundError:
            return False
        return target_is_named and project.name.casefold().replace(" ", "") in normalised
