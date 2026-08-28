import json
from typing import Any

import httpx

from jarvis_api.assistants import Assistant
from jarvis_api.tools import ToolCall


class OllamaUnavailableError(RuntimeError):
    """Raised when the configured local Ollama runtime cannot complete a request."""


class OllamaService:
    def __init__(self, base_url: str, model: str, timeout: float = 60.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    async def is_available(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                response = await client.get(f"{self.base_url}/api/tags")
                response.raise_for_status()
            return True
        except (httpx.HTTPError, ValueError):
            return False

    async def chat(self, message: str, assistant: Assistant) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "stream": False,
            "messages": [
                {"role": "system", "content": assistant.system_prompt},
                {"role": "user", "content": message},
            ],
        }
        return await self._chat_request(payload)

    async def route_tool(
        self,
        message: str,
        assistant: Assistant,
        routing_context: dict[str, object],
    ) -> ToolCall | None:
        routing_prompt = (
            "Decide whether the user request requires one approved project tool. "
            'Return JSON only as {"name": <tool name or null>, "arguments": {}}. '
            "Use only the supplied tool names and project IDs. Never invent an ID, path, "
            "command, result, or tool. Use open_project only for an explicit request to open "
            "a project in VS Code or Finder. Context: " + json.dumps(routing_context)
        )
        payload: dict[str, Any] = {
            "model": self.model,
            "stream": False,
            "format": "json",
            "messages": [
                {"role": "system", "content": routing_prompt},
                {"role": "user", "content": message},
            ],
        }
        content = await self._chat_request(payload)
        try:
            decision = json.loads(content)
            if decision.get("name") is None:
                return None
            return ToolCall.model_validate(decision)
        except (json.JSONDecodeError, AttributeError, TypeError, ValueError):
            return None

    async def chat_grounded(
        self,
        message: str,
        assistant: Assistant,
        tool_name: str,
        tool_result: dict[str, object],
    ) -> str:
        grounding_prompt = (
            assistant.system_prompt
            + "\nAnswer the user's project question using only the approved tool result below. "
            "Do not add repository facts that are absent. If the result is insufficient, say so. "
            f"Tool: {tool_name}\nResult: {json.dumps(tool_result)}"
        )
        payload: dict[str, Any] = {
            "model": self.model,
            "stream": False,
            "messages": [
                {"role": "system", "content": grounding_prompt},
                {"role": "user", "content": message},
            ],
        }
        return await self._chat_request(payload)

    async def _chat_request(self, payload: dict[str, Any]) -> str:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(f"{self.base_url}/api/chat", json=payload)
                response.raise_for_status()
                content = response.json()["message"]["content"]
            if not isinstance(content, str) or not content.strip():
                raise ValueError("Ollama returned an empty response")
            return content.strip()
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as error:
            raise OllamaUnavailableError(
                "Ollama is unavailable or returned an invalid response"
            ) from error
