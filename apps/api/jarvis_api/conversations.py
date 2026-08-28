import json
import threading
import time
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass, field
from uuid import UUID, uuid4


class ConversationNotFoundError(LookupError):
    pass


class ConversationExpiredError(LookupError):
    pass


@dataclass(frozen=True)
class ConversationTurn:
    user: str
    assistant: str
    tool_observation: dict[str, object] | None = None

    @property
    def character_count(self) -> int:
        observation = json.dumps(self.tool_observation) if self.tool_observation else ""
        return len(self.user) + len(self.assistant) + len(observation)


@dataclass
class ConversationSession:
    id: UUID
    created_at: float
    last_accessed_at: float
    turns: list[ConversationTurn] = field(default_factory=list)


class ConversationStore:
    def __init__(
        self,
        ttl_seconds: int = 1800,
        max_turns: int = 12,
        max_characters: int = 12000,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.ttl_seconds = ttl_seconds
        self.max_turns = max_turns
        self.max_characters = max_characters
        self._clock = clock
        self._sessions: dict[UUID, ConversationSession] = {}
        self._lock = threading.Lock()

    def create(self) -> ConversationSession:
        now = self._clock()
        session = ConversationSession(id=uuid4(), created_at=now, last_accessed_at=now)
        with self._lock:
            self._sessions[session.id] = session
        return deepcopy(session)

    def get(self, conversation_id: UUID) -> ConversationSession:
        with self._lock:
            session = self._get_active(conversation_id)
            session.last_accessed_at = self._clock()
            return deepcopy(session)

    def append(
        self,
        conversation_id: UUID,
        user: str,
        assistant: str,
        tool_observation: dict[str, object] | None = None,
    ) -> ConversationSession:
        turn = ConversationTurn(
            user=user,
            assistant=assistant,
            tool_observation=deepcopy(tool_observation),
        )
        with self._lock:
            session = self._get_active(conversation_id)
            session.turns.append(turn)
            session.last_accessed_at = self._clock()
            self._trim(session)
            return deepcopy(session)

    def delete(self, conversation_id: UUID) -> None:
        with self._lock:
            self._get_active(conversation_id)
            del self._sessions[conversation_id]

    def _get_active(self, conversation_id: UUID) -> ConversationSession:
        session = self._sessions.get(conversation_id)
        if session is None:
            raise ConversationNotFoundError(str(conversation_id))
        if self._clock() - session.last_accessed_at > self.ttl_seconds:
            del self._sessions[conversation_id]
            raise ConversationExpiredError(str(conversation_id))
        return session

    def _trim(self, session: ConversationSession) -> None:
        while len(session.turns) > self.max_turns:
            session.turns.pop(0)
        while len(session.turns) > 1 and self._character_count(session) > self.max_characters:
            session.turns.pop(0)

    @staticmethod
    def _character_count(session: ConversationSession) -> int:
        return sum(turn.character_count for turn in session.turns)
