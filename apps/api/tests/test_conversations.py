from uuid import uuid4

import pytest

from jarvis_api.conversations import (
    ConversationExpiredError,
    ConversationNotFoundError,
    ConversationStore,
)


def test_sessions_are_independent_and_deletable() -> None:
    store = ConversationStore()
    first = store.create()
    second = store.create()
    store.append(first.id, "alpha", "one")

    assert [turn.user for turn in store.get(first.id).turns] == ["alpha"]
    assert store.get(second.id).turns == []

    store.delete(first.id)
    with pytest.raises(ConversationNotFoundError):
        store.get(first.id)


def test_history_trims_oldest_turns_deterministically() -> None:
    store = ConversationStore(max_turns=2, max_characters=10_000)
    session = store.create()
    store.append(session.id, "first", "response")
    store.append(session.id, "second", "response")
    store.append(session.id, "third", "response")

    assert [turn.user for turn in store.get(session.id).turns] == ["second", "third"]


def test_history_trims_by_character_limit_but_keeps_current_turn() -> None:
    store = ConversationStore(max_turns=10, max_characters=20)
    session = store.create()
    store.append(session.id, "first", "1234567890")
    store.append(session.id, "second", "1234567890")

    turns = store.get(session.id).turns
    assert len(turns) == 1
    assert turns[0].user == "second"


def test_session_expiry_is_controlled() -> None:
    now = [100.0]
    store = ConversationStore(ttl_seconds=30, clock=lambda: now[0])
    session = store.create()
    now[0] = 131.0

    with pytest.raises(ConversationExpiredError):
        store.get(session.id)
    with pytest.raises(ConversationNotFoundError):
        store.get(session.id)


def test_unknown_session_is_rejected() -> None:
    with pytest.raises(ConversationNotFoundError):
        ConversationStore().get(uuid4())
