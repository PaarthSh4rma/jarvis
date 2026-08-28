import os
import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from jarvis_api.main import app, get_project_service
from jarvis_api.projects import ProjectService


def run_git(path: Path, *arguments: str, env: dict[str, str] | None = None) -> None:
    subprocess.run(
        ["git", "-C", str(path), *arguments],
        check=True,
        capture_output=True,
        env=env,
    )


def make_git_project(root: Path, name: str = "alpha") -> Path:
    project = root / name
    project.mkdir()
    run_git(project, "init", "-b", "main")
    (project / "pyproject.toml").write_text("[project]\nname='alpha'\n")
    run_git(project, "add", "pyproject.toml")
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Test User",
        "GIT_AUTHOR_EMAIL": "test@example.invalid",
        "GIT_COMMITTER_NAME": "Test User",
        "GIT_COMMITTER_EMAIL": "test@example.invalid",
    }
    run_git(project, "commit", "-m", "Initial foundation", env=env)
    return project


def test_discovers_projects_and_ignores_plain_directories(tmp_path: Path) -> None:
    (tmp_path / "plain").mkdir()
    node_project = tmp_path / "node-app"
    node_project.mkdir()
    (node_project / "package.json").write_text("{}")

    projects = ProjectService(tmp_path).discover()

    assert [project.name for project in projects] == ["node-app"]
    assert projects[0].technologies == ("Node.js",)
    assert projects[0].path == node_project.resolve()


def test_git_metadata_and_dirty_detection(tmp_path: Path) -> None:
    project = make_git_project(tmp_path)
    clean = ProjectService(tmp_path).discover()[0]
    assert clean.branch == "main"
    assert clean.is_dirty is False
    assert clean.latest_commit_message == "Initial foundation"
    assert clean.latest_commit_timestamp is not None

    (project / "notes.txt").write_text("uncommitted")
    dirty = ProjectService(tmp_path).discover()[0]
    assert dirty.is_dirty is True


def test_symlink_escaping_root_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "projects"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (outside / "package.json").write_text("{}")
    (root / "escape").symlink_to(outside, target_is_directory=True)

    assert ProjectService(root).discover() == []


def test_project_id_prevents_path_traversal(tmp_path: Path) -> None:
    make_git_project(tmp_path)
    service = ProjectService(tmp_path)
    app.dependency_overrides[get_project_service] = lambda: service
    try:
        with TestClient(app) as client:
            traversal = client.get("/projects/..%2F..%2Fetc")
            unknown = client.get("/projects/0000000000000000")
    finally:
        app.dependency_overrides.clear()

    assert traversal.status_code in {404, 422}
    assert unknown.status_code == 404


def test_project_api_summary_and_failure(tmp_path: Path) -> None:
    project = make_git_project(tmp_path)
    (project / "dirty.txt").write_text("change")
    service = ProjectService(tmp_path)
    app.dependency_overrides[get_project_service] = lambda: service
    try:
        with TestClient(app) as client:
            listing = client.get("/projects")
            project_id = listing.json()["projects"][0]["id"]
            detail = client.get(f"/projects/{project_id}")
    finally:
        app.dependency_overrides.clear()

    assert listing.status_code == 200
    assert listing.json()["count"] == 1
    assert listing.json()["dirty_count"] == 1
    assert "path" not in listing.json()["projects"][0]
    assert detail.status_code == 200


def test_open_project_uses_allowlisted_macos_command(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "sample"
    project.mkdir()
    (project / "package.json").write_text("{}")
    service = ProjectService(tmp_path)
    project_id = service.discover()[0].id
    calls: list[list[str]] = []

    def fake_run(command: list[str], **kwargs) -> None:
        calls.append(command)

    monkeypatch.setattr(subprocess, "run", fake_run)
    service.open_project(project_id, "vscode")

    assert calls == [["open", "-a", "Visual Studio Code", str(project.resolve())]]
