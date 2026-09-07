import re
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from sqlalchemy import Column, DateTime, MetaData, String, Table, delete, insert, select, update
from sqlalchemy.engine import Engine

MemoryScope = Literal["user", "project"]
SECRET_PATTERN = re.compile(
    r"\b(?:api[-_ ]?key|password|passwd|access[-_ ]?token|refresh[-_ ]?token|"
    r"private[-_ ]?key|secret)\b",
    re.IGNORECASE,
)


class MemoryNotFoundError(LookupError):
    pass


class MemoryLimitError(ValueError):
    pass


@dataclass(frozen=True)
class MemoryEntry:
    id: str
    scope: MemoryScope
    project_id: str | None
    content: str
    created_at: datetime
    updated_at: datetime


metadata = MetaData()
memories = Table(
    "memories",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("scope", String(16), nullable=False),
    Column("project_id", String(16), nullable=True, index=True),
    Column("content", String, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)


class MemoryStore:
    def __init__(
        self,
        engine: Engine,
        *,
        max_user_entries: int = 50,
        max_project_entries: int = 25,
        max_characters: int = 500,
        max_injected_characters: int = 2000,
    ) -> None:
        self.engine = engine
        self.max_user_entries = max_user_entries
        self.max_project_entries = max_project_entries
        self.max_characters = max_characters
        self.max_injected_characters = max_injected_characters
        self._write_lock = threading.Lock()

    def initialize(self) -> None:
        metadata.create_all(self.engine, tables=[memories])

    def add(
        self, scope: MemoryScope, content: str, project_id: str | None = None
    ) -> MemoryEntry:
        content = self._validate(scope, content, project_id)
        with self._write_lock:
            existing = self.list(scope=scope, project_id=project_id)
            limit = self.max_user_entries if scope == "user" else self.max_project_entries
            if len(existing) >= limit:
                raise MemoryLimitError(f"The {scope} memory limit has been reached.")
            now = datetime.now(UTC)
            entry = MemoryEntry(str(uuid4()), scope, project_id, content, now, now)
            with self.engine.begin() as connection:
                connection.execute(insert(memories).values(**entry.__dict__))
        return entry

    def list(
        self, *, scope: MemoryScope | None = None, project_id: str | None = None
    ) -> list[MemoryEntry]:
        query = select(memories)
        if scope is not None:
            query = query.where(memories.c.scope == scope)
        if project_id is not None:
            query = query.where(memories.c.project_id == project_id)
        query = query.order_by(memories.c.updated_at.asc(), memories.c.id.asc())
        with self.engine.connect() as connection:
            rows = connection.execute(query).mappings().all()
        return [MemoryEntry(**dict(row)) for row in rows]

    def get(self, memory_id: str) -> MemoryEntry:
        with self.engine.connect() as connection:
            row = connection.execute(
                select(memories).where(memories.c.id == memory_id)
            ).mappings().first()
        if row is None:
            raise MemoryNotFoundError(memory_id)
        return MemoryEntry(**dict(row))

    def update(self, memory_id: str, content: str) -> MemoryEntry:
        current = self.get(memory_id)
        content = self._validate(current.scope, content, current.project_id)
        now = datetime.now(UTC)
        with self.engine.begin() as connection:
            connection.execute(
                update(memories)
                .where(memories.c.id == memory_id)
                .values(content=content, updated_at=now)
            )
        return MemoryEntry(
            current.id,
            current.scope,
            current.project_id,
            content,
            current.created_at,
            now,
        )

    def delete(self, memory_id: str) -> None:
        with self.engine.begin() as connection:
            result = connection.execute(delete(memories).where(memories.c.id == memory_id))
        if result.rowcount == 0:
            raise MemoryNotFoundError(memory_id)

    def context(self, project_id: str | None = None) -> tuple[MemoryEntry, ...]:
        entries: list[MemoryEntry] = []
        if project_id is not None:
            entries.extend(self.list(scope="project", project_id=project_id))
        entries.extend(self.list(scope="user"))
        selected: list[MemoryEntry] = []
        used = 0
        for entry in entries:
            cost = len(entry.content)
            if used + cost > self.max_injected_characters:
                break
            selected.append(entry)
            used += cost
        return tuple(selected)

    def _validate(
        self, scope: MemoryScope, content: str, project_id: str | None
    ) -> str:
        content = content.strip()
        if not content:
            raise MemoryLimitError("Memory content must contain text.")
        if len(content) > self.max_characters:
            raise MemoryLimitError(
                f"Memory content exceeds {self.max_characters} characters."
            )
        if SECRET_PATTERN.search(content):
            raise MemoryLimitError("Memory cannot store credentials or secrets.")
        if scope == "project" and project_id is None:
            raise MemoryLimitError("Project memory requires a project ID.")
        if scope == "user" and project_id is not None:
            raise MemoryLimitError("User memory cannot have a project ID.")
        return content
