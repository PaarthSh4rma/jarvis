"""Create deterministic, local Git repositories for the public JARVIS demo."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEMO_ROOT = ROOT / ".demo" / "projects"
PROJECTS = (
    ("RaceBrain", "Python", "pyproject.toml", "[project]\nname = 'racebrain'\n"),
    ("ExoHunter", "Node.js", "package.json", '{"name":"exohunter","private":true}\n'),
    (
        "ClientOps Copilot",
        "Python",
        "pyproject.toml",
        "[project]\nname = 'clientops-copilot'\n",
    ),
)


def run_git(path: Path, *arguments: str, env: dict[str, str] | None = None) -> None:
    subprocess.run(
        ["git", "-C", str(path), *arguments],
        check=True,
        capture_output=True,
        env=env,
    )


def main() -> None:
    # This script owns only the ignored .demo directory and makes reruns reproducible.
    if DEMO_ROOT.parent.exists():
        shutil.rmtree(DEMO_ROOT.parent)
    DEMO_ROOT.mkdir(parents=True)
    commit_env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "JARVIS Demo",
        "GIT_AUTHOR_EMAIL": "demo@example.invalid",
        "GIT_COMMITTER_NAME": "JARVIS Demo",
        "GIT_COMMITTER_EMAIL": "demo@example.invalid",
        "GIT_AUTHOR_DATE": "2026-09-01T09:00:00+10:00",
        "GIT_COMMITTER_DATE": "2026-09-01T09:00:00+10:00",
    }
    for name, _technology, marker, content in PROJECTS:
        project = DEMO_ROOT / name
        project.mkdir()
        run_git(project, "init", "-b", "main")
        (project / marker).write_text(content, encoding="utf-8")
        run_git(project, "add", marker)
        run_git(project, "commit", "-m", "Initial demo snapshot", env=commit_env)
    print(f"Prepared {len(PROJECTS)} clean demo repositories in .demo/projects")


if __name__ == "__main__":
    main()
