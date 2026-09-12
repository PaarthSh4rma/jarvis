import hashlib
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

PROJECT_MARKERS = {
    "package.json": "Node.js",
    "pyproject.toml": "Python",
    "requirements.txt": "Python",
    "Cargo.toml": "Rust",
    "go.mod": "Go",
}
GIT_TIMEOUT_SECONDS = 3.0
DEMO_PROJECT_ORDER = ("RaceBrain", "ExoHunter", "ClientOps Copilot")


class ProjectNotFoundError(LookupError):
    pass


class ProjectLaunchError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProjectMetadata:
    id: str
    name: str
    path: Path
    is_git_repository: bool
    branch: str | None
    is_dirty: bool | None
    latest_commit_message: str | None
    latest_commit_timestamp: str | None
    technologies: tuple[str, ...]
    latest_commit_at: datetime | None = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        """Normalize external Git timestamps once, at metadata construction."""
        parsed: datetime | None = None
        if self.latest_commit_timestamp:
            try:
                parsed = datetime.fromisoformat(self.latest_commit_timestamp)
            except ValueError:
                pass
        if parsed is not None:
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            else:
                parsed = parsed.astimezone(UTC)
        object.__setattr__(self, "latest_commit_at", parsed)

    def public_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "name": self.name,
            "is_git_repository": self.is_git_repository,
            "branch": self.branch,
            "is_dirty": self.is_dirty,
            "latest_commit_message": self.latest_commit_message,
            "latest_commit_timestamp": self.latest_commit_timestamp,
            "technologies": list(self.technologies),
        }


class ProjectService:
    def __init__(self, projects_root: Path, git_timeout: float = GIT_TIMEOUT_SECONDS) -> None:
        self.root = projects_root.expanduser().resolve()
        self.git_timeout = git_timeout

    def discover(self) -> list[ProjectMetadata]:
        if not self.root.is_dir():
            return []

        projects: list[ProjectMetadata] = []
        for child in sorted(self.root.iterdir(), key=lambda path: path.name.casefold()):
            if not child.is_dir():
                continue
            try:
                resolved = child.resolve(strict=True)
                resolved.relative_to(self.root)
            except (FileNotFoundError, RuntimeError, ValueError):
                continue
            if not self._is_project(resolved):
                continue
            projects.append(self._inspect(resolved))
        return projects

    def get(self, project_id: str) -> ProjectMetadata:
        project = next((item for item in self.discover() if item.id == project_id), None)
        if project is None:
            raise ProjectNotFoundError(project_id)
        return project

    def recent(self, limit: int = 5) -> list[ProjectMetadata]:
        no_timestamp = datetime.min.replace(tzinfo=UTC)
        projects = sorted(
            self.discover(), key=lambda project: (project.name.casefold(), project.id)
        )
        return sorted(
            projects,
            key=lambda project: project.latest_commit_at or no_timestamp,
            reverse=True,
        )[:limit]

    def open_project(self, project_id: str, target: Literal["vscode", "finder"]) -> None:
        project = self.get(project_id)
        command = (
            ["open", "-a", "Visual Studio Code", str(project.path)]
            if target == "vscode"
            else ["open", str(project.path)]
        )
        try:
            subprocess.run(command, check=True, timeout=5.0, capture_output=True)
        except (OSError, subprocess.SubprocessError) as error:
            raise ProjectLaunchError(f"Could not open {project.name} in {target}") from error

    def _is_project(self, path: Path) -> bool:
        return (path / ".git").is_dir() or any(
            (path / marker).is_file() for marker in PROJECT_MARKERS
        )

    def _inspect(self, path: Path) -> ProjectMetadata:
        is_git = (path / ".git").is_dir()
        technologies = tuple(
            dict.fromkeys(
                technology
                for marker, technology in PROJECT_MARKERS.items()
                if (path / marker).is_file()
            )
        )
        if is_git:
            branch = self._git(path, "branch", "--show-current") or None
            status = self._git(path, "status", "--porcelain")
            commit_message = self._git(path, "log", "-1", "--format=%s") or None
            commit_timestamp = self._git(path, "log", "-1", "--format=%cI") or None
            is_dirty: bool | None = None if status is None else bool(status)
        else:
            branch = commit_message = commit_timestamp = None
            is_dirty = None
        identifier = hashlib.sha256(str(path).encode()).hexdigest()[:16]
        return ProjectMetadata(
            id=identifier,
            name=path.name,
            path=path,
            is_git_repository=is_git,
            branch=branch,
            is_dirty=is_dirty,
            latest_commit_message=commit_message,
            latest_commit_timestamp=commit_timestamp,
            technologies=technologies,
        )

    def _git(self, path: Path, *arguments: str) -> str | None:
        try:
            result = subprocess.run(
                ["git", "-C", str(path), *arguments],
                check=True,
                capture_output=True,
                text=True,
                timeout=self.git_timeout,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        return result.stdout.strip()


class DemoProjectService(ProjectService):
    """Project discovery with a stable presentation order for the isolated demo fixture."""

    def discover(self) -> list[ProjectMetadata]:
        projects = super().discover()
        order = {name: index for index, name in enumerate(DEMO_PROJECT_ORDER)}
        return sorted(
            projects,
            key=lambda project: (order.get(project.name, len(order)), project.name.casefold()),
        )
