from pathlib import Path

import pytest

from jarvis_api.projects import ProjectService
from jarvis_api.tools import (
    ExternalActionDeniedError,
    ToolArgumentError,
    ToolCall,
    ToolRegistry,
    UnknownToolError,
)


def project_registry(tmp_path: Path) -> tuple[ToolRegistry, str]:
    project = tmp_path / "sample"
    project.mkdir()
    (project / "go.mod").write_text("module example.invalid/sample\n")
    service = ProjectService(tmp_path)
    return ToolRegistry(service), service.discover()[0].id


def test_validated_project_tool(tmp_path: Path) -> None:
    registry, project_id = project_registry(tmp_path)
    result = registry.execute(
        ToolCall(name="get_project_status", arguments={"project_id": project_id})
    )
    assert result["project"]["name"] == "sample"  # type: ignore[index]


def test_unknown_tool_is_rejected(tmp_path: Path) -> None:
    registry, _ = project_registry(tmp_path)
    with pytest.raises(UnknownToolError):
        registry.execute(ToolCall(name="run_shell", arguments={}))


def test_malformed_arguments_are_rejected(tmp_path: Path) -> None:
    registry, _ = project_registry(tmp_path)
    with pytest.raises(ToolArgumentError):
        registry.execute(ToolCall(name="get_project_status", arguments={"project_id": "../../etc"}))


def test_open_project_requires_external_intent(tmp_path: Path) -> None:
    registry, project_id = project_registry(tmp_path)
    with pytest.raises(ExternalActionDeniedError):
        registry.execute(
            ToolCall(
                name="open_project",
                arguments={"project_id": project_id, "target": "vscode"},
            )
        )
