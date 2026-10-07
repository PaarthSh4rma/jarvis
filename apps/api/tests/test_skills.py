from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from jarvis_api.main import app, get_skill_registry
from jarvis_api.skills import (
    SkillNotFoundError,
    SkillRegistry,
    SkillValidationError,
)


def write_skill(
    root: Path,
    directory: str,
    *,
    name: str | None = None,
    description: str = "Inspect a project safely.",
    scope: str = "project",
    version: str = "1",
    procedure: str = "# Procedure\n\n1. Inspect approved project state.",
) -> Path:
    skill_dir = root / directory
    skill_dir.mkdir(parents=True)
    path = skill_dir / "SKILL.md"
    path.write_text(
        "---\n"
        f"name: {name or directory}\n"
        f"description: {description}\n"
        f"scope: {scope}\n"
        f"version: {version}\n"
        "---\n\n"
        f"{procedure}\n"
    )
    return path


def test_registry_discovers_valid_skills_in_deterministic_name_order(tmp_path: Path) -> None:
    write_skill(tmp_path, "z-directory", name="project-summary")
    write_skill(tmp_path, "a-directory", name="project-health-check")

    skills = SkillRegistry(tmp_path).discover()

    assert [skill.name for skill in skills] == ["project-health-check", "project-summary"]
    assert skills[0].scope == "project"
    assert skills[0].version == 1


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"scope": "system"}, "scope"),
        ({"version": "latest"}, "version"),
        ({"name": "Wéird-Skill"}, "name"),
        ({"description": ""}, "metadata"),
    ],
)
def test_registry_rejects_malformed_metadata(
    tmp_path: Path, changes: dict[str, str], message: str
) -> None:
    write_skill(tmp_path, "candidate", **changes)

    with pytest.raises(SkillValidationError, match=message):
        SkillRegistry(tmp_path).discover()


def test_registry_rejects_malformed_frontmatter(tmp_path: Path) -> None:
    path = write_skill(tmp_path, "candidate")
    path.write_text("name: candidate\nNo frontmatter boundary")

    with pytest.raises(SkillValidationError, match="frontmatter"):
        SkillRegistry(tmp_path).discover()


def test_registry_rejects_oversized_skill(tmp_path: Path) -> None:
    write_skill(tmp_path, "large", procedure="x" * 500)

    with pytest.raises(SkillValidationError, match="file-size"):
        SkillRegistry(tmp_path, max_file_bytes=200).discover()


def test_registry_enforces_procedure_and_skill_count_bounds(tmp_path: Path) -> None:
    write_skill(tmp_path, "one", procedure="procedure exceeds tiny configured budget")
    with pytest.raises(SkillValidationError, match="procedure"):
        SkillRegistry(tmp_path, max_procedure_characters=10).discover()

    write_skill(tmp_path, "two")
    with pytest.raises(SkillValidationError, match="skill limit"):
        SkillRegistry(tmp_path, max_skills=1).discover()


def test_registry_rejects_duplicate_names(tmp_path: Path) -> None:
    write_skill(tmp_path, "one", name="same-skill")
    write_skill(tmp_path, "two", name="same-skill")

    with pytest.raises(SkillValidationError, match="duplicate"):
        SkillRegistry(tmp_path).discover()


def test_registry_rejects_symlink_escape(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    outside = tmp_path / "outside"
    root.mkdir()
    write_skill(outside, "escaped")
    (root / "escaped").symlink_to(outside / "escaped", target_is_directory=True)

    with pytest.raises(SkillValidationError, match="escapes"):
        SkillRegistry(root).discover()


def test_registry_rejects_path_like_lookup(tmp_path: Path) -> None:
    write_skill(tmp_path, "safe-skill")

    with pytest.raises(SkillNotFoundError):
        SkillRegistry(tmp_path).get("../safe-skill")


def test_selection_index_is_bounded_and_never_contains_procedures(tmp_path: Path) -> None:
    write_skill(
        tmp_path,
        "safe-skill",
        description="A short safe description.",
        procedure="SECRET PROCEDURE BODY",
    )

    index = SkillRegistry(tmp_path, max_index_characters=200).selection_index()

    assert index[0]["name"] == "safe-skill"
    assert "procedure" not in index[0]
    assert "SECRET PROCEDURE BODY" not in str(index)
    assert SkillRegistry(tmp_path, max_index_characters=20).selection_index() == ()


def test_skills_api_exposes_only_safe_metadata(tmp_path: Path) -> None:
    write_skill(tmp_path, "project-summary", procedure="PRIVATE PROCEDURE")
    app.dependency_overrides[get_skill_registry] = lambda: SkillRegistry(tmp_path)
    try:
        with TestClient(app) as client:
            response = client.get("/skills")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {
        "skills": [
            {
                "name": "project-summary",
                "description": "Inspect a project safely.",
                "scope": "project",
                "version": 1,
            }
        ],
        "count": 1,
    }
    serialized = response.text
    assert str(tmp_path) not in serialized
    assert "PRIVATE PROCEDURE" not in serialized


def test_skills_api_reports_registry_failure(tmp_path: Path) -> None:
    app.dependency_overrides[get_skill_registry] = lambda: SkillRegistry(tmp_path / "missing")
    try:
        with TestClient(app) as client:
            response = client.get("/skills")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json() == {"detail": "Skill registry unavailable."}
