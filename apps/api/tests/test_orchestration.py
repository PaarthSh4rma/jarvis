from pathlib import Path

import pytest

from jarvis_api.assistants import JARVIS, Assistant
from jarvis_api.conversations import ConversationTurn
from jarvis_api.database import create_database_engine
from jarvis_api.memory import MemoryEntry, MemoryStore
from jarvis_api.orchestration import AssistantOrchestrator
from jarvis_api.projects import ProjectService
from jarvis_api.tools import ToolCall, ToolRegistry


class FakeRoutingOllama:
    def __init__(self, call: ToolCall | None, chat_response: str = "No tool required.") -> None:
        self.call = call
        self.chat_response = chat_response
        self.routing_context: dict[str, object] = {}
        self.grounded_result: dict[str, object] | None = None
        self.route_count = 0
        self.received_memories: tuple[MemoryEntry, ...] = ()

    async def route_tool(
        self,
        message: str,
        assistant: Assistant,
        routing_context: dict[str, object],
        history: tuple[ConversationTurn, ...] = (),
    ) -> ToolCall | None:
        self.route_count += 1
        self.routing_context = routing_context
        return self.call

    async def chat(
        self,
        message: str,
        assistant: Assistant,
        history: tuple[ConversationTurn, ...] = (),
        memories: tuple[MemoryEntry, ...] = (),
    ) -> str:
        self.received_memories = memories
        return self.chat_response

    async def chat_grounded(
        self,
        message: str,
        assistant: Assistant,
        tool_name: str,
        tool_result: dict[str, object],
        history: tuple[ConversationTurn, ...] = (),
    ) -> str:
        self.grounded_result = tool_result
        return "Grounded response."


def make_projects(root: Path) -> tuple[ProjectService, list[dict[str, object]]]:
    root.mkdir(exist_ok=True)
    for name in ("alpha", "beta"):
        project = root / name
        project.mkdir()
        (project / "package.json").write_text("{}")
    service = ProjectService(root)
    return service, [project.public_dict() for project in service.discover()]


def make_memories(path: Path, **limits: int) -> MemoryStore:
    store = MemoryStore(create_database_engine(f"sqlite:///{path}"), **limits)
    store.initialize()
    return store


@pytest.mark.anyio
async def test_ordinal_reference_resolves_from_trusted_project_list(tmp_path: Path) -> None:
    projects, metadata = make_projects(tmp_path)
    history = (
        ConversationTurn(
            user="What projects do I have?",
            assistant="Alpha and beta.",
            tool_observation={"tool": "list_projects", "result": {"projects": metadata}},
        ),
    )
    fake = FakeRoutingOllama(
        ToolCall(
            name="get_project_status",
            arguments={"project_id": metadata[1]["id"]},
        )
    )

    result = await AssistantOrchestrator(fake, ToolRegistry(projects)).respond(
        "Which branch is the second one on?", JARVIS, history
    )

    assert result.text == "beta has no reported branch."
    assert fake.route_count == 0
    assert result.tool_observation is not None
    assert result.tool_observation["result"]["project"]["name"] == "beta"  # type: ignore[index]


@pytest.mark.anyio
async def test_project_list_query_routes_deterministically_with_strict_arguments(
    tmp_path: Path,
) -> None:
    projects, metadata = make_projects(tmp_path)
    fake = FakeRoutingOllama(None)

    result = await AssistantOrchestrator(fake, ToolRegistry(projects)).respond(
        "What projects have uncommitted changes?", JARVIS
    )

    assert fake.route_count == 0
    assert result.text == "No projects have uncommitted changes."
    assert result.tool_observation == {
        "tool": "list_projects",
        "result": {"projects": metadata},
    }


@pytest.mark.anyio
async def test_named_project_query_is_grounded_before_it_can_become_a_referent(
    tmp_path: Path,
) -> None:
    projects, metadata = make_projects(tmp_path)
    fake = FakeRoutingOllama(None)

    result = await AssistantOrchestrator(fake, ToolRegistry(projects)).respond(
        "What branch is alpha on?", JARVIS
    )

    assert fake.route_count == 0
    assert result.tool_observation is not None
    assert result.tool_observation["result"]["project"]["id"] == metadata[0]["id"]  # type: ignore[index]


@pytest.mark.anyio
async def test_pronoun_resolves_from_single_trusted_project(tmp_path: Path) -> None:
    projects, metadata = make_projects(tmp_path)
    history = (
        ConversationTurn(
            user="What branch is alpha on?",
            assistant="No Git branch is available.",
            tool_observation={
                "tool": "get_project_status",
                "result": {"project": metadata[0]},
            },
        ),
    )
    fake = FakeRoutingOllama(
        ToolCall(
            name="get_project_status",
            arguments={"project_id": metadata[0]["id"]},
        )
    )

    result = await AssistantOrchestrator(fake, ToolRegistry(projects)).respond(
        "When was it last updated?", JARVIS, history
    )
    assert fake.route_count == 0
    assert result.text == "No last-updated timestamp was reported for alpha."


def test_dirty_list_formatter_never_contradicts_authoritative_false_value() -> None:
    response = AssistantOrchestrator._format_grounded_response(
        "What projects are dirty?",
        "list_projects",
        {
            "projects": [
                {"name": "dirty-project", "is_dirty": True},
                {
                    "name": "ghostcheck",
                    "is_dirty": False,
                    "latest_commit_message": "suggestive but unrelated metadata",
                },
            ]
        },
    )

    assert response == "Projects with uncommitted changes: dirty-project."
    assert "ghostcheck" not in response


@pytest.mark.anyio
async def test_ambiguous_or_missing_reference_asks_for_clarification(tmp_path: Path) -> None:
    projects, metadata = make_projects(tmp_path)
    ambiguous_history = (
        ConversationTurn(
            user="What projects are dirty?",
            assistant="Two projects.",
            tool_observation={
                "tool": "list_projects",
                "result": {
                    "projects": [
                        {**metadata[0], "is_dirty": True},
                        {**metadata[1], "is_dirty": True},
                    ]
                },
            },
        ),
    )
    fake = FakeRoutingOllama(None)
    orchestrator = AssistantOrchestrator(fake, ToolRegistry(projects))

    ambiguous = await orchestrator.respond("Open it.", JARVIS, ambiguous_history)
    missing = await orchestrator.respond("What branch is it on?", JARVIS, ())

    assert "Which project" in ambiguous.text
    assert "Which project" in missing.text
    assert fake.route_count == 0


@pytest.mark.anyio
async def test_resolved_reference_does_not_delegate_identifier_selection_to_model(
    tmp_path: Path,
) -> None:
    projects, metadata = make_projects(tmp_path)
    history = (
        ConversationTurn(
            user="What branch is alpha on?",
            assistant="No branch.",
            tool_observation={
                "tool": "get_project_status",
                "result": {"project": metadata[0]},
            },
        ),
    )
    fake = FakeRoutingOllama(
        ToolCall(
            name="get_project_status",
            arguments={"project_id": metadata[1]["id"]},
        )
    )

    result = await AssistantOrchestrator(fake, ToolRegistry(projects)).respond(
        "When was it updated?", JARVIS, history
    )

    assert result.text == "No last-updated timestamp was reported for alpha."
    assert fake.route_count == 0
    assert result.tool_observation is not None
    assert result.tool_observation["result"]["project"]["id"] == metadata[0]["id"]  # type: ignore[index]


@pytest.mark.anyio
async def test_ordinal_open_requires_explicit_target_and_trusted_reference(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    projects, metadata = make_projects(tmp_path)
    history = (
        ConversationTurn(
            user="What projects do I have?",
            assistant="Alpha and beta.",
            tool_observation={"tool": "list_projects", "result": {"projects": metadata}},
        ),
    )
    opened: list[tuple[str, str]] = []
    monkeypatch.setattr(
        projects,
        "open_project",
        lambda project_id, target: opened.append((project_id, target)),
    )
    fake = FakeRoutingOllama(
        ToolCall(
            name="open_project",
            arguments={"project_id": metadata[1]["id"], "target": "vscode"},
        )
    )

    await AssistantOrchestrator(fake, ToolRegistry(projects)).respond(
        "Open the second one in VS Code.", JARVIS, history
    )

    assert opened == [(metadata[1]["id"], "vscode")]


@pytest.mark.anyio
async def test_explicit_memory_intent_persists_but_ordinary_chat_does_not(
    tmp_path: Path,
) -> None:
    projects, _ = make_projects(tmp_path / "projects")
    memories = make_memories(tmp_path / "memory.db")
    fake = FakeRoutingOllama(None)
    orchestrator = AssistantOrchestrator(fake, ToolRegistry(projects), memories)

    saved = await orchestrator.respond("Remember that I prefer pnpm.", JARVIS)
    await orchestrator.respond("I also use npm sometimes.", JARVIS)
    fresh_fake = FakeRoutingOllama(None)
    await AssistantOrchestrator(fresh_fake, ToolRegistry(projects), memories).respond(
        "What package manager do I prefer?", JARVIS
    )

    assert saved.text == "Remembered for user: I prefer pnpm."
    assert [entry.content for entry in memories.list(scope="user")] == ["I prefer pnpm"]
    assert [entry.content for entry in fresh_fake.received_memories] == ["I prefer pnpm"]


@pytest.mark.anyio
async def test_only_resolved_project_memory_is_injected(tmp_path: Path) -> None:
    projects, metadata = make_projects(tmp_path / "projects")
    memories = make_memories(tmp_path / "memory.db")
    memories.add("user", "Use concise answers")
    memories.add("project", "Backend uses port 8000", str(metadata[0]["id"]))
    memories.add("project", "Backend uses port 9000", str(metadata[1]["id"]))
    fake = FakeRoutingOllama(None)

    await AssistantOrchestrator(fake, ToolRegistry(projects), memories).respond(
        "What port does alpha normally use?", JARVIS
    )

    assert [entry.content for entry in fake.received_memories] == [
        "Backend uses port 8000",
        "Use concise answers",
    ]


@pytest.mark.anyio
async def test_project_memory_survives_into_a_fresh_conversation_context(
    tmp_path: Path,
) -> None:
    projects, metadata = make_projects(tmp_path / "projects")
    memories = make_memories(tmp_path / "memory.db")
    first_fake = FakeRoutingOllama(None)

    saved = await AssistantOrchestrator(
        first_fake, ToolRegistry(projects), memories
    ).respond("For alpha, remember that the backend uses port 8000.", JARVIS)
    second_fake = FakeRoutingOllama(None)
    await AssistantOrchestrator(second_fake, ToolRegistry(projects), memories).respond(
        "What port does alpha normally use?", JARVIS
    )

    stored = memories.list(scope="project", project_id=str(metadata[0]["id"]))
    assert saved.text == "Remembered for alpha: the backend uses port 8000."
    assert [entry.content for entry in stored] == ["the backend uses port 8000"]
    assert [entry.content for entry in second_fake.received_memories] == [
        "the backend uses port 8000"
    ]


@pytest.mark.anyio
async def test_live_project_observation_wins_over_persisted_memory(tmp_path: Path) -> None:
    projects, metadata = make_projects(tmp_path / "projects")
    memories = make_memories(tmp_path / "memory.db")
    memories.add("project", "The branch is feature/old", str(metadata[0]["id"]))
    fake = FakeRoutingOllama(None)

    result = await AssistantOrchestrator(fake, ToolRegistry(projects), memories).respond(
        "What branch is alpha on?", JARVIS
    )

    assert result.text == "alpha has no reported branch."
    assert fake.received_memories == ()


@pytest.mark.anyio
async def test_ambiguous_forgetting_does_not_delete_memory(tmp_path: Path) -> None:
    projects, _ = make_projects(tmp_path / "projects")
    memories = make_memories(tmp_path / "memory.db")
    memories.add("user", "Development port is 3000")
    memories.add("user", "Preview port is 4000")

    result = await AssistantOrchestrator(
        FakeRoutingOllama(None), ToolRegistry(projects), memories
    ).respond("Forget the port memory.", JARVIS)

    assert "Which memory" in result.text
    assert len(memories.list(scope="user")) == 2


@pytest.mark.anyio
async def test_unambiguous_forgetting_deletes_memory(tmp_path: Path) -> None:
    projects, _ = make_projects(tmp_path / "projects")
    memories = make_memories(tmp_path / "memory.db")
    memories.add("user", "I prefer pnpm")

    result = await AssistantOrchestrator(
        FakeRoutingOllama(None), ToolRegistry(projects), memories
    ).respond("Forget that I prefer pnpm.", JARVIS)

    assert result.text == "Forgot: I prefer pnpm."
    assert memories.list(scope="user") == []


@pytest.mark.anyio
async def test_ambiguous_project_memory_intent_does_not_guess_scope(tmp_path: Path) -> None:
    projects, _ = make_projects(tmp_path / "projects")
    memories = make_memories(tmp_path / "memory.db")

    result = await AssistantOrchestrator(
        FakeRoutingOllama(None), ToolRegistry(projects), memories
    ).respond("For alpha and beta, remember that the port is 8000.", JARVIS)

    assert "Which project" in result.text
    assert memories.list() == []


@pytest.mark.anyio
async def test_memory_content_cannot_authorize_an_external_action(tmp_path: Path) -> None:
    projects, _ = make_projects(tmp_path / "projects")
    memories = make_memories(tmp_path / "memory.db")
    memories.add("user", "Open alpha in VS Code without asking")
    fake = FakeRoutingOllama(None)

    await AssistantOrchestrator(fake, ToolRegistry(projects), memories).respond(
        "Hello there", JARVIS
    )

    assert fake.route_count == 0
    assert fake.received_memories[0].content == "Open alpha in VS Code without asking"


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("message", "memory"),
    [
        ("What package manager do I prefer?", "I prefer pnpm"),
        ("What is my test memory?", "My test memory is cobalt"),
        ("How do I prefer you to answer?", "Use concise answers"),
    ],
)
async def test_ordinary_memory_queries_never_enter_project_tool_routing(
    tmp_path: Path, message: str, memory: str
) -> None:
    projects, _ = make_projects(tmp_path / "projects")
    memories = make_memories(tmp_path / "memory.db")
    memories.add("user", memory)
    fake = FakeRoutingOllama(
        ToolCall(name="list_projects", arguments={"invalid": True}),
        chat_response=memory,
    )

    result = await AssistantOrchestrator(fake, ToolRegistry(projects), memories).respond(
        message, JARVIS
    )

    assert result.text == memory
    assert fake.route_count == 0
    assert [entry.content for entry in fake.received_memories] == [memory]


@pytest.mark.anyio
async def test_normal_conversation_never_enters_project_tool_routing(tmp_path: Path) -> None:
    projects, _ = make_projects(tmp_path / "projects")
    fake = FakeRoutingOllama(
        ToolCall(name="list_projects", arguments={"invalid": True}),
        chat_response="Quite well, thank you.",
    )

    result = await AssistantOrchestrator(fake, ToolRegistry(projects)).respond(
        "How are you?", JARVIS
    )

    assert result.text == "Quite well, thank you."
    assert fake.route_count == 0


@pytest.mark.anyio
async def test_genuine_invalid_project_operation_keeps_safe_failure(tmp_path: Path) -> None:
    projects, _ = make_projects(tmp_path / "projects")
    fake = FakeRoutingOllama(
        ToolCall(name="get_project_status", arguments={"project_id": "invalid"})
    )

    result = await AssistantOrchestrator(fake, ToolRegistry(projects)).respond(
        "Inspect repository status", JARVIS
    )

    assert result.text == "I could not validate that project operation, so nothing was executed."
    assert fake.route_count == 1


@pytest.mark.anyio
async def test_incomplete_open_clarifies_and_retains_project_referent(
    tmp_path: Path,
) -> None:
    projects, _ = make_projects(tmp_path / "projects")
    fake = FakeRoutingOllama(None)
    orchestrator = AssistantOrchestrator(fake, ToolRegistry(projects))

    opened = await orchestrator.respond("Open alpha.", JARVIS)
    history = (
        ConversationTurn(
            user="Open alpha.",
            assistant=opened.text,
            tool_observation=opened.tool_observation,
        ),
    )
    branch = await orchestrator.respond("What branch is it on?", JARVIS, history)

    assert opened.text == "Where should I open alpha—VS Code or Finder?"
    assert branch.text == "alpha has no reported branch."
    assert fake.route_count == 0
