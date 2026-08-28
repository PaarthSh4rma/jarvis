from pathlib import Path

import pytest

from jarvis_api.assistants import JARVIS, Assistant
from jarvis_api.conversations import ConversationTurn
from jarvis_api.orchestration import AssistantOrchestrator
from jarvis_api.projects import ProjectService
from jarvis_api.tools import ToolCall, ToolRegistry


class FakeRoutingOllama:
    def __init__(self, call: ToolCall | None) -> None:
        self.call = call
        self.routing_context: dict[str, object] = {}
        self.grounded_result: dict[str, object] | None = None
        self.route_count = 0

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
    ) -> str:
        return "No tool required."

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
    for name in ("alpha", "beta"):
        project = root / name
        project.mkdir()
        (project / "package.json").write_text("{}")
    service = ProjectService(root)
    return service, [project.public_dict() for project in service.discover()]


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
