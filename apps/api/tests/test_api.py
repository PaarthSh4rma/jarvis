from pathlib import Path

from fastapi.testclient import TestClient

from jarvis_api.assistants import Assistant
from jarvis_api.main import app, get_ollama_service, get_project_service
from jarvis_api.ollama import OllamaUnavailableError
from jarvis_api.projects import ProjectService
from jarvis_api.tools import ToolCall


class FakeOllama:
    model = "test-model"

    def __init__(
        self,
        available: bool = True,
        response: str = "At your disposal.",
        tool_call: ToolCall | None = None,
    ) -> None:
        self.available = available
        self.response = response
        self.received_message: str | None = None
        self.received_assistant: Assistant | None = None
        self.tool_call = tool_call
        self.grounded_result: dict[str, object] | None = None

    async def is_available(self) -> bool:
        return self.available

    async def chat(self, message: str, assistant: Assistant) -> str:
        self.received_message = message
        self.received_assistant = assistant
        if not self.available:
            raise OllamaUnavailableError("offline")
        return self.response

    async def route_tool(
        self,
        message: str,
        assistant: Assistant,
        routing_context: dict[str, object],
    ) -> ToolCall | None:
        if not self.available:
            raise OllamaUnavailableError("offline")
        return self.tool_call

    async def chat_grounded(
        self,
        message: str,
        assistant: Assistant,
        tool_name: str,
        tool_result: dict[str, object],
    ) -> str:
        self.grounded_result = tool_result
        return self.response


def client_for(fake: FakeOllama, projects_root: Path | None = None) -> TestClient:
    app.dependency_overrides[get_ollama_service] = lambda: fake
    if projects_root is not None:
        app.dependency_overrides[get_project_service] = lambda: ProjectService(projects_root)
    return TestClient(app)


def teardown_function() -> None:
    app.dependency_overrides.clear()


def test_health_reports_ollama_and_model() -> None:
    with client_for(FakeOllama()) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "jarvis-api",
        "version": "0.3.0",
        "ollama": "online",
        "model": "test-model",
    }


def test_health_gracefully_reports_ollama_offline() -> None:
    with client_for(FakeOllama(available=False)) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["ollama"] == "offline"


def test_chat_preflight_accepts_127_loopback_frontend() -> None:
    with client_for(FakeOllama()) as client:
        response = client.options(
            "/chat",
            headers={
                "Origin": "http://127.0.0.1:3000",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:3000"


def test_successful_chat_uses_jarvis_personality(tmp_path: Path) -> None:
    fake = FakeOllama(response="Good evening. Systems are nominal.")
    with client_for(fake, tmp_path) as client:
        response = client.post("/chat", json={"message": "  Status report  "})

    assert response.status_code == 200
    assert response.json() == {
        "response": "Good evening. Systems are nominal.",
        "model": "test-model",
        "assistant": "jarvis",
    }
    assert fake.received_message == "Status report"
    assert fake.received_assistant is not None
    assert "local personal and development assistant" in fake.received_assistant.system_prompt


def test_chat_reports_ollama_unavailable(tmp_path: Path) -> None:
    with client_for(FakeOllama(available=False), tmp_path) as client:
        response = client.post("/chat", json={"message": "Hello"})

    assert response.status_code == 503
    assert response.json()["detail"].startswith("Ollama is unavailable")


def test_chat_rejects_empty_and_malformed_input(tmp_path: Path) -> None:
    with client_for(FakeOllama(), tmp_path) as client:
        empty = client.post("/chat", json={"message": "   "})
        missing = client.post("/chat", json={})
        too_long = client.post("/chat", json={"message": "x" * 4001})

    assert empty.status_code == 422
    assert missing.status_code == 422
    assert too_long.status_code == 422


def test_chat_routes_through_mocked_project_tool(tmp_path: Path) -> None:
    project = tmp_path / "jarvis"
    project.mkdir()
    (project / "package.json").write_text("{}")
    project_id = ProjectService(tmp_path).discover()[0].id
    fake = FakeOllama(
        response="Jarvis is a Node.js project.",
        tool_call=ToolCall(name="get_project_status", arguments={"project_id": project_id}),
    )

    with client_for(fake, tmp_path) as client:
        response = client.post("/chat", json={"message": "What technology does jarvis use?"})

    assert response.status_code == 200
    assert response.json()["response"] == "Jarvis is a Node.js project."
    assert fake.grounded_result is not None
    assert fake.grounded_result["project"]["name"] == "jarvis"  # type: ignore[index]
