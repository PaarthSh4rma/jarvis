"""Durable local mission records; no scheduler or execution side effects."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Column, Integer, MetaData, String, Table, insert, select, update
from sqlalchemy.engine import Engine


class RecordNotFoundError(LookupError):
    pass


class RecordConflictError(ValueError):
    pass


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class MissionType(StrEnum):
    CODE_CHANGE = "CODE_CHANGE"
    PROJECT_REVIEW = "PROJECT_REVIEW"
    JOB_APPLICATION = "JOB_APPLICATION"
    RESEARCH = "RESEARCH"
    INTERVIEW_PREP = "INTERVIEW_PREP"
    MONEY_EXPERIMENT = "MONEY_EXPERIMENT"
    ADMIN = "ADMIN"


class MissionStatus(StrEnum):
    DRAFT = "DRAFT"
    READY = "READY"
    RUNNING = "RUNNING"
    WAITING_FOR_APPROVAL = "WAITING_FOR_APPROVAL"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


Title = Annotated[str, Field(min_length=1, max_length=160)]
Goal = Annotated[str, Field(min_length=1, max_length=4000)]
ProjectId = Annotated[str, Field(pattern=r"^[a-f0-9]{16}$")]


class MissionCreate(StrictModel):
    type: MissionType
    title: Title
    goal: Goal
    project_id: ProjectId | None = None
    context: str | None = Field(default=None, max_length=4000)
    requested_by: str = Field(default="local-user", min_length=1, max_length=100)


class MissionPatch(StrictModel):
    # Leave room for the next revision in SQLite's signed 64-bit integer range.
    expected_revision: int = Field(ge=1, le=2**63 - 2, strict=True)
    title: Title | None = None
    goal: Goal | None = None
    project_id: ProjectId | None = None
    context: str | None = Field(default=None, max_length=4000)
    # Execution states are reserved until a real executor can attest to them.
    status: Literal["DRAFT", "READY", "CANCELLED"] | None = None

    @model_validator(mode="after")
    def meaningful_patch(self) -> "MissionPatch":
        if not self.model_fields_set - {"expected_revision"}:
            raise ValueError("No changes supplied")
        for field in ("title", "goal", "status"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self


class Mission(MissionCreate):
    id: UUID
    status: MissionStatus
    created_at: datetime
    updated_at: datetime
    revision: int
    external_execution_id: str | None = Field(default=None, max_length=200)
    result_summary: str | None = Field(default=None, max_length=4000)
    failure_summary: str | None = Field(default=None, max_length=2000)


metadata = MetaData()
missions = Table(
    "missions",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("type", String(32), nullable=False),
    Column("title", String(160), nullable=False),
    Column("goal", String(4000), nullable=False),
    Column("project_id", String(16)),
    Column("context", String(4000)),
    Column("status", String(32), nullable=False, index=True),
    Column("requested_by", String(100), nullable=False),
    Column("created_at", String(40), nullable=False),
    Column("updated_at", String(40), nullable=False),
    Column("revision", Integer, nullable=False),
    Column("external_execution_id", String(200)),
    Column("result_summary", String(4000)),
    Column("failure_summary", String(2000)),
)


class MissionStore:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def initialize(self) -> None:
        metadata.create_all(self.engine, tables=[missions])

    def create(self, request: MissionCreate) -> Mission:
        now = datetime.now(UTC)
        record = Mission(
            **request.model_dump(),
            id=uuid4(),
            status=MissionStatus.DRAFT,
            created_at=now,
            updated_at=now,
            revision=1,
        )
        with self.engine.begin() as connection:
            connection.execute(insert(missions).values(**record.model_dump(mode="json")))
        return record

    def get(self, mission_id: UUID) -> Mission:
        with self.engine.connect() as connection:
            row = (
                connection.execute(select(missions).where(missions.c.id == str(mission_id)))
                .mappings()
                .first()
            )
        if row is None:
            raise RecordNotFoundError("Mission not found")
        return Mission.model_validate(dict(row))

    def list(self, limit: int = 50, offset: int = 0) -> list[Mission]:
        with self.engine.connect() as connection:
            rows = (
                connection.execute(
                    select(missions)
                    .order_by(missions.c.created_at.desc(), missions.c.id)
                    .limit(min(max(limit, 1), 100))
                    .offset(min(max(offset, 0), 2**63 - 1))
                )
                .mappings()
                .all()
            )
        return [Mission.model_validate(dict(row)) for row in rows]

    def update(self, mission_id: UUID, request: MissionPatch) -> Mission:
        current = self.get(mission_id)
        if current.status not in {MissionStatus.DRAFT, MissionStatus.READY}:
            raise RecordConflictError("Mission is not editable")
        values = request.model_dump(mode="json", exclude_unset=True, exclude={"expected_revision"})
        values.update(updated_at=datetime.now(UTC).isoformat(), revision=current.revision + 1)
        with self.engine.begin() as connection:
            result = connection.execute(
                update(missions)
                .where(
                    missions.c.id == str(mission_id),
                    missions.c.revision == request.expected_revision,
                    missions.c.revision == current.revision,
                )
                .values(**values)
            )
            if result.rowcount != 1:
                raise RecordConflictError("Mission changed; reload before updating")
            row = (
                connection.execute(select(missions).where(missions.c.id == str(mission_id)))
                .mappings()
                .one()
            )
        return Mission.model_validate(dict(row))
