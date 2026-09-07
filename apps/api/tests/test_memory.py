from pathlib import Path

import pytest

from jarvis_api.database import create_database_engine
from jarvis_api.memory import MemoryLimitError, MemoryNotFoundError, MemoryStore


def make_store(path: Path, **limits: int) -> MemoryStore:
    store = MemoryStore(create_database_engine(f"sqlite:///{path}"), **limits)
    store.initialize()
    return store


def test_user_and_project_memory_persist_across_store_instances(tmp_path: Path) -> None:
    database = tmp_path / "memory.db"
    first = make_store(database)
    user = first.add("user", "I prefer pnpm")
    project = first.add("project", "Backend uses port 8000", "a" * 16)

    second = make_store(database)

    assert second.get(user.id).content == "I prefer pnpm"
    assert second.get(project.id).project_id == "a" * 16


def test_add_list_update_delete_and_deterministic_ordering(tmp_path: Path) -> None:
    store = make_store(tmp_path / "memory.db")
    first = store.add("user", "First")
    second = store.add("user", "Second")

    assert [entry.id for entry in store.list(scope="user")] == [first.id, second.id]
    updated = store.update(first.id, "Updated")
    assert updated.content == "Updated"
    assert [entry.id for entry in store.list(scope="user")] == [second.id, first.id]
    store.delete(second.id)
    assert [entry.id for entry in store.list(scope="user")] == [first.id]
    with pytest.raises(MemoryNotFoundError):
        store.get(second.id)


def test_scope_bounds_and_oversized_memory_are_rejected(tmp_path: Path) -> None:
    store = make_store(
        tmp_path / "memory.db",
        max_user_entries=1,
        max_project_entries=1,
        max_characters=10,
    )
    store.add("user", "short")
    store.add("project", "alpha", "a" * 16)

    with pytest.raises(MemoryLimitError, match="user memory limit"):
        store.add("user", "second")
    with pytest.raises(MemoryLimitError, match="project memory limit"):
        store.add("project", "second", "a" * 16)
    with pytest.raises(MemoryLimitError, match="exceeds 10"):
        store.add("project", "too many characters", "b" * 16)


def test_project_separation_and_bounded_context(tmp_path: Path) -> None:
    store = make_store(tmp_path / "memory.db", max_injected_characters=12)
    store.add("user", "user")
    store.add("project", "alpha", "a" * 16)
    store.add("project", "unrelated", "b" * 16)

    context = store.context("a" * 16)

    assert [(entry.scope, entry.content) for entry in context] == [
        ("project", "alpha"),
        ("user", "user"),
    ]
    assert all(entry.project_id != "b" * 16 for entry in context)


def test_scope_shape_is_strict(tmp_path: Path) -> None:
    store = make_store(tmp_path / "memory.db")
    with pytest.raises(MemoryLimitError, match="requires a project"):
        store.add("project", "fact")
    with pytest.raises(MemoryLimitError, match="cannot have"):
        store.add("user", "fact", "a" * 16)
    with pytest.raises(MemoryLimitError, match="credentials or secrets"):
        store.add("user", "My API key is example-value")
