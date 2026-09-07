from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from jarvis_api.assistants import Assistant
from jarvis_api.conversations import ConversationStore, ConversationTurn
from jarvis_api.main import (
    app,
    get_conversation_store,
    get_memory_store,
    get_ollama_service,
    get_project_service,
)
from jarvis_api.memory import MemoryStore
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
        self.received_history: tuple[ConversationTurn, ...] = ()

    async def is_available(self) -> bool:
        return self.available

    async def chat(
        self,
        message: str,
        assistant: Assistant,
        history: tuple[ConversationTurn, ...] = (),
    ) -> str:
        self.received_message = message
        self.received_assistant = assistant
        self.received_history = history
        if not self.available:
            raise OllamaUnavailableError("offline")
        return self.response

    async def route_tool(
        self,
        message: str,
        assistant: Assistant,
        routing_context: dict[str, object],
        history: tuple[ConversationTurn, ...] = (),
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
        history: tuple[ConversationTurn, ...] = (),
    ) -> str:
        self.grounded_result = tool_result
        return self.response


def client_for(
    fake: FakeOllama,
    projects_root: Path | None = None,
    conversations: ConversationStore | None = None,
    memories: MemoryStore | None = None,
) -> TestClient:
    session_store = conversations or ConversationStore()
    memory = memories or MemoryStore(
        create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    )
    memory.initialize()
    app.dependency_overrides[get_ollama_service] = lambda: fake
    if projects_root is not None:
        app.dependency_overrides[get_project_service] = lambda: ProjectService(projects_root)
    app.dependency_overrides[get_conversation_store] = lambda: session_store
    app.dependency_overrides[get_memory_store] = lambda: memory
    return TestClient(app)


def create_conversation(client: TestClient) -> str:
    response = client.post("/conversations")
    assert response.status_code == 201
    return response.json()["conversation_id"]


def teardown_function() -> None:
    app.dependency_overrides.clear()


def test_health_reports_ollama_and_model() -> None:
    with client_for(FakeOllama()) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "jarvis-api",
        "version": "0.5.0",
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
        conversation_id = create_conversation(client)
        response = client.post(
            "/chat",
            json={"message": "  Status report  ", "conversation_id": conversation_id},
        )

    assert response.status_code == 200
    assert response.json() == {
        "response": "Good evening. Systems are nominal.",
        "model": "test-model",
        "assistant": "jarvis",
        "conversation_id": conversation_id,
    }
    assert fake.received_message == "Status report"
    assert fake.received_assistant is not None
    assert "local personal and development assistant" in fake.received_assistant.system_prompt


def test_chat_reports_ollama_unavailable(tmp_path: Path) -> None:
    with client_for(FakeOllama(available=False), tmp_path) as client:
        conversation_id = create_conversation(client)
        response = client.post(
            "/chat", json={"message": "Hello", "conversation_id": conversation_id}
        )

    assert response.status_code == 503
    assert response.json()["detail"].startswith("Ollama is unavailable")


def test_chat_rejects_empty_and_malformed_input(tmp_path: Path) -> None:
    with client_for(FakeOllama(), tmp_path) as client:
        conversation_id = create_conversation(client)
        empty = client.post(
            "/chat", json={"message": "   ", "conversation_id": conversation_id}
        )
        missing = client.post("/chat", json={})
        too_long = client.post(
            "/chat", json={"message": "x" * 4001, "conversation_id": conversation_id}
        )

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
        conversation_id = create_conversation(client)
        response = client.post(
            "/chat",
            json={
                "message": "What technology does jarvis use?",
                "conversation_id": conversation_id,
            },
        )

    assert response.status_code == 200
    assert response.json()["response"] == "jarvis uses Node.js."


def test_conversation_lifecycle_and_missing_session(tmp_path: Path) -> None:
    with client_for(FakeOllama(), tmp_path) as client:
        created = client.post("/conversations")
        conversation_id = created.json()["conversation_id"]
        deleted = client.delete(f"/conversations/{conversation_id}")
        missing = client.post(
            "/chat",
            json={"message": "Hello", "conversation_id": conversation_id},
        )
        invalid = client.post(
            "/chat", json={"message": "Hello", "conversation_id": "../../etc"}
        )

    assert created.status_code == 201
    assert created.json()["max_turns"] == 12
    assert deleted.status_code == 204
    assert missing.status_code == 404
    assert invalid.status_code == 422


def test_session_history_is_continuous_and_isolated(tmp_path: Path) -> None:
    fake = FakeOllama(response="Acknowledged.")
    with client_for(fake, tmp_path) as client:
        first_session = create_conversation(client)
        second_session = create_conversation(client)
        client.post(
            "/chat", json={"message": "Remember alpha", "conversation_id": first_session}
        )
        client.post(
            "/chat", json={"message": "What did I say?", "conversation_id": first_session}
        )
        first_history = fake.received_history
        client.post(
            "/chat", json={"message": "What did I say?", "conversation_id": second_session}
        )
        second_history = fake.received_history

    assert [turn.user for turn in first_history] == ["Remember alpha"]
    assert second_history == ()


def test_expired_session_returns_controlled_response(tmp_path: Path) -> None:
    now = [10.0]
    store = ConversationStore(ttl_seconds=30, clock=lambda: now[0])
    with client_for(FakeOllama(), tmp_path, store) as client:
        conversation_id = create_conversation(client)
        now[0] = 41.0
        response = client.post(
            "/chat",
            json={"message": "Continue", "conversation_id": conversation_id},
        )

    assert response.status_code == 410
    assert response.json()["detail"] == "Conversation expired. Start a new session."


def test_memory_api_crud_and_scope_filtering(tmp_path: Path) -> None:
    project = tmp_path / "alpha"
    project.mkdir()
    (project / "package.json").write_text("{}")
    project_id = ProjectService(tmp_path).discover()[0].id

    with client_for(FakeOllama(), tmp_path) as client:
        user = client.post(
            "/memory", json={"scope": "user", "content": "I prefer pnpm"}
        )
        project_memory = client.post(
            "/memory",
            json={
                "scope": "project",
                "project_id": project_id,
                "content": "Backend uses port 8000",
            },
        )
        listed = client.get(f"/memory?scope=project&project_id={project_id}")
        updated = client.patch(
            f"/memory/{user.json()['id']}", json={"content": "I prefer npm"}
        )
        deleted = client.delete(f"/memory/{project_memory.json()['id']}")

    assert user.status_code == 201
    assert project_memory.status_code == 201
    assert project_memory.json()["project_name"] == "alpha"
    assert [entry["content"] for entry in listed.json()["memories"]] == [
        "Backend uses port 8000"
    ]
    assert updated.json()["content"] == "I prefer npm"
    assert deleted.status_code == 204


def test_memory_api_rejects_invalid_project_and_bounds(tmp_path: Path) -> None:
    memory = MemoryStore(
        create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        ),
        max_characters=5,
    )
    memory.initialize()

    with client_for(FakeOllama(), tmp_path, memories=memory) as client:
        unknown = client.post(
            "/memory",
            json={
                "scope": "project",
                "project_id": "a" * 16,
                "content": "fact",
            },
        )
        malformed = client.post(
            "/memory",
            json={"scope": "project", "project_id": "../../etc", "content": "fact"},
        )
        oversized = client.post(
            "/memory", json={"scope": "user", "content": "too long"}
        )

    assert unknown.status_code == 404
    assert malformed.status_code == 422
    assert oversized.status_code == 409
