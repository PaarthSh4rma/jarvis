import asyncio
import threading
from pathlib import Path
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from jarvis_api.assistants import Assistant
from jarvis_api.conversations import ConversationStore, ConversationTurn
from jarvis_api.database import create_database_engine
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
        self.received_memories = ()
        self.route_count = 0
        self.received_skill = None

    async def is_available(self) -> bool:
        return self.available

    async def chat(
        self,
        message: str,
        assistant: Assistant,
        history: tuple[ConversationTurn, ...] = (),
        memories: tuple = (),
    ) -> str:
        self.received_message = message
        self.received_assistant = assistant
        self.received_history = history
        self.received_memories = memories
        if not self.available:
            raise OllamaUnavailableError("offline")
        return self.response

    async def chat_stream(
        self,
        message: str,
        assistant: Assistant,
        history: tuple[ConversationTurn, ...] = (),
        memories: tuple = (),
    ):
        self.received_message = message
        self.received_history = history
        self.received_memories = memories
        if not self.available:
            raise OllamaUnavailableError("offline")
        midpoint = max(1, len(self.response) // 2)
        yield self.response[:midpoint]
        yield self.response[midpoint:]

    async def route_tool(
        self,
        message: str,
        assistant: Assistant,
        routing_context: dict[str, object],
        history: tuple[ConversationTurn, ...] = (),
    ) -> ToolCall | None:
        self.route_count += 1
        if not self.available:
            raise OllamaUnavailableError("offline")
        return self.tool_call

    async def route_skill(self, message, assistant, skill_index, history=()):
        return None

    async def chat_grounded(
        self,
        message: str,
        assistant: Assistant,
        tool_name: str,
        tool_result: dict[str, object],
        history: tuple[ConversationTurn, ...] = (),
        memories: tuple = (),
        skill=None,
    ) -> str:
        self.grounded_result = tool_result
        self.received_skill = skill
        return self.response

    async def chat_grounded_stream(
        self,
        message,
        assistant,
        tool_name,
        tool_result,
        history=(),
        memories=(),
        skill=None,
    ):
        self.grounded_result = tool_result
        self.received_skill = skill
        midpoint = max(1, len(self.response) // 2)
        yield self.response[:midpoint]
        yield self.response[midpoint:]


class SlowFakeOllama(FakeOllama):
    def __init__(self) -> None:
        super().__init__()
        self.started = threading.Event()
        self.release = threading.Event()

    async def chat_stream(self, message, assistant, history=(), memories=()):
        self.started.set()
        await asyncio.to_thread(self.release.wait, 2)
        yield "Done."


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
        "version": "0.7.0",
        "ollama": "online",
        "model": "test-model",
        "demo_mode": False,
    }


def test_health_gracefully_reports_ollama_offline() -> None:
    with client_for(FakeOllama(available=False)) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["ollama"] == "offline"


def test_run_http_streams_response_and_enforces_ownership() -> None:
    conversations = ConversationStore()
    with client_for(
        FakeOllama(response="Streamed response."), conversations=conversations
    ) as client:
        conversation_id = create_conversation(client)
        created = client.post(
            "/runs", json={"message": "Hello", "conversation_id": conversation_id}
        )
        assert created.status_code == 201
        run_id = created.json()["run_id"]
        events = client.get(
            f"/runs/{run_id}/events", params={"conversation_id": conversation_id}
        )
        wrong_owner = client.get(
            f"/runs/{run_id}",
            params={"conversation_id": "22222222-2222-4222-8222-222222222222"},
        )

    assert events.status_code == 200
    assert "assistant.delta" in events.text
    assert "run.completed" in events.text
    assert wrong_owner.status_code == 403
    assert conversations.get(UUID(conversation_id)).turns[0].assistant == "Streamed response."


def test_explicit_skill_executes_through_run_http_and_emits_safe_events(tmp_path: Path) -> None:
    project = tmp_path / "ExoHunter"
    project.mkdir()
    (project / "package.json").write_text("{}")
    fake = FakeOllama(response="Grounded skill response.")
    conversations = ConversationStore()
    with client_for(fake, projects_root=tmp_path, conversations=conversations) as client:
        conversation_id = create_conversation(client)
        created = client.post(
            "/runs",
            json={
                "message": "Use project-summary on ExoHunter.",
                "conversation_id": conversation_id,
            },
        )
        events = client.get(
            f"/runs/{created.json()['run_id']}/events",
            params={"conversation_id": conversation_id},
        )

    assert created.status_code == 201
    assert events.status_code == 200
    assert "skill.selected" in events.text
    assert "skill.completed" in events.text
    assert "project-summary" in events.text
    assert "Selected skill procedure" not in events.text
    assert str(tmp_path) not in events.text
    assert fake.received_skill.name == "project-summary"
    assert len(conversations.get(UUID(conversation_id)).turns) == 1


def test_explicit_memory_mutation_works_through_run_runtime() -> None:
    memory = MemoryStore(
        create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    )
    with client_for(FakeOllama(), memories=memory) as client:
        conversation_id = create_conversation(client)
        created = client.post(
            "/runs",
            json={
                "message": "Remember that I prefer pnpm.",
                "conversation_id": conversation_id,
            },
        )
        events = client.get(
            f"/runs/{created.json()['run_id']}/events",
            params={"conversation_id": conversation_id},
        )

    assert created.status_code == 201
    assert "Remembered for user: I prefer pnpm." in events.text
    assert [entry.content for entry in memory.list(scope="user")] == ["I prefer pnpm"]


def test_run_http_enforces_conversation_concurrency_and_allows_independent_sessions() -> None:
    fake = SlowFakeOllama()
    with client_for(fake) as client:
        first = create_conversation(client)
        second = create_conversation(client)
        run_a = client.post(
            "/runs", json={"message": "How are you?", "conversation_id": first}
        )
        assert run_a.status_code == 201, run_a.text
        duplicate = client.post("/runs", json={"message": "Again", "conversation_id": first})
        assert fake.started.wait(timeout=1)
        independent = client.post("/runs", json={"message": "Other", "conversation_id": second})
        cancelled_a = client.post(
            f"/runs/{run_a.json()['run_id']}/cancel", json={"conversation_id": first}
        )
        cancelled_c = client.post(
            f"/runs/{independent.json()['run_id']}/cancel",
            json={"conversation_id": second},
        )
        terminal_a = client.get(
            f"/runs/{run_a.json()['run_id']}/events", params={"conversation_id": first}
        )
        fake.release.set()
        replacement = client.post(
            "/runs", json={"message": "Replacement", "conversation_id": first}
        )
        if replacement.status_code == 201:
            client.post(
                f"/runs/{replacement.json()['run_id']}/cancel",
                json={"conversation_id": first},
            )

    assert run_a.status_code == independent.status_code == 201
    assert duplicate.status_code == 409
    assert cancelled_a.status_code == cancelled_c.status_code == 200
    assert "run.cancelled" in terminal_a.text
    assert replacement.status_code == 201


def test_run_http_returns_bounded_errors_for_malformed_and_unknown_ids() -> None:
    conversation_id = "11111111-1111-4111-8111-111111111111"
    unknown = "99999999-9999-4999-8999-999999999999"
    with client_for(FakeOllama()) as client:
        malformed = client.get(
            "/runs/not-a-uuid", params={"conversation_id": conversation_id}
        )
        status_response = client.get(
            f"/runs/{unknown}", params={"conversation_id": conversation_id}
        )
        cancel_response = client.post(
            f"/runs/{unknown}/cancel", json={"conversation_id": conversation_id}
        )

    assert malformed.status_code == 422
    assert status_response.status_code == cancel_response.status_code == 404
    assert status_response.json() == {"detail": "Run not found."}
    assert cancel_response.json() == {"detail": "Run not found."}


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


def test_http_memory_retrieval_bypasses_invented_project_tool_calls(
    tmp_path: Path,
) -> None:
    fake = FakeOllama(
        response="You prefer pnpm.",
        tool_call=ToolCall(name="get_project_status", arguments={"project_id": "invalid"}),
    )
    with client_for(fake, tmp_path) as client:
        first_session = create_conversation(client)
        saved = client.post(
            "/chat",
            json={
                "message": "Remember that I prefer pnpm.",
                "conversation_id": first_session,
            },
        )
        fresh_session = create_conversation(client)
        retrieved = client.post(
            "/chat",
            json={
                "message": "What package manager do I prefer?",
                "conversation_id": fresh_session,
            },
        )

    assert saved.json()["response"] == "Remembered for user: I prefer pnpm."
    assert retrieved.json()["response"] == "You prefer pnpm."
    assert [entry.content for entry in fake.received_memories] == ["I prefer pnpm"]
    assert fake.route_count == 0


def test_http_memory_survives_store_reinstantiation_and_backend_session_reset(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'persistent.db'}"
    first_store = MemoryStore(create_database_engine(database_url))
    first_store.initialize()
    with client_for(FakeOllama(), tmp_path, memories=first_store) as client:
        session = create_conversation(client)
        client.post(
            "/chat",
            json={
                "message": "Remember that I prefer pnpm.",
                "conversation_id": session,
            },
        )

    second_store = MemoryStore(create_database_engine(database_url))
    second_store.initialize()
    fake = FakeOllama(response="pnpm.")
    with client_for(fake, tmp_path, memories=second_store) as client:
        fresh_session = create_conversation(client)
        response = client.post(
            "/chat",
            json={
                "message": "What package manager do I prefer?",
                "conversation_id": fresh_session,
            },
        )

    assert response.json()["response"] == "pnpm."
    assert [entry.content for entry in fake.received_memories] == ["I prefer pnpm"]


def test_http_ordinary_conversation_never_falls_into_project_validation(
    tmp_path: Path,
) -> None:
    fake = FakeOllama(
        response="Quite well, thank you.",
        tool_call=ToolCall(name="list_projects", arguments={"unexpected": True}),
    )
    with client_for(fake, tmp_path) as client:
        session = create_conversation(client)
        response = client.post(
            "/chat", json={"message": "How are you?", "conversation_id": session}
        )

    assert response.json()["response"] == "Quite well, thank you."
    assert fake.route_count == 0


def test_http_non_explicit_statement_is_not_persisted(tmp_path: Path) -> None:
    memory = MemoryStore(create_database_engine(f"sqlite:///{tmp_path / 'memory.db'}"))
    memory.initialize()
    with client_for(FakeOllama(response="Noted."), tmp_path, memories=memory) as client:
        session = create_conversation(client)
        client.post(
            "/chat",
            json={"message": "I used yarn yesterday.", "conversation_id": session},
        )
        fresh_session = create_conversation(client)
        client.post(
            "/chat",
            json={"message": "What package manager do I use?", "conversation_id": fresh_session},
        )

    assert memory.list() == []
