from typing import Any

import pytest

from jarvis_api.assistants import JARVIS
from jarvis_api.ollama import OllamaService


@pytest.mark.anyio
async def test_grounded_prompt_treats_explicit_tool_values_as_authoritative(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = OllamaService("http://localhost:11434", "test-model")
    captured: dict[str, Any] = {}

    async def capture_payload(payload: dict[str, Any]) -> str:
        captured.update(payload)
        return "ghostcheck has a clean working tree."

    monkeypatch.setattr(service, "_chat_request", capture_payload)
    response = await service.chat_grounded(
        "Does ghostcheck have uncommitted changes?",
        JARVIS,
        "get_project_status",
        {
            "project": {
                "name": "ghostcheck",
                "is_dirty": False,
                "latest_commit_message": "Work in progress",
            }
        },
    )

    system_prompt = captured["messages"][0]["content"]
    assert "Treat every explicit tool field as authoritative" in system_prompt
    assert "is_dirty=false means the working tree is clean" in system_prompt
    assert "commit messages do not override that value" in system_prompt
    assert '"is_dirty": false' in system_prompt
    assert response == "ghostcheck has a clean working tree."
