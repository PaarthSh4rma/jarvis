"""Human-decision records only. Resolution never dispatches an action."""

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import Field
from sqlalchemy import Column, ForeignKey, String, Table, insert, select, update
from sqlalchemy.engine import Engine

from jarvis_api.missions import (
    RecordConflictError,
    RecordNotFoundError,
    StrictModel,
    metadata,
    missions,
)

ApprovalStatus = Literal["PENDING", "APPROVED", "REJECTED", "CANCELLED"]


class ApprovalCreate(StrictModel):
    mission_id: UUID
    action_type: str = Field(min_length=1, max_length=80, pattern=r"^[A-Z][A-Z0-9_]*$")
    summary: str = Field(min_length=1, max_length=1000)
    risk_context: str = Field(min_length=1, max_length=2000)


class ApprovalResolve(StrictModel):
    status: Literal["APPROVED", "REJECTED", "CANCELLED"]
    resolution_note: str | None = Field(default=None, max_length=2000)


class Approval(ApprovalCreate):
    id: UUID
    status: ApprovalStatus
    created_at: datetime
    resolved_at: datetime | None = None
    resolution_note: str | None = Field(default=None, max_length=2000)


approvals = Table(
    "approvals",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("mission_id", String(36), ForeignKey("missions.id"), nullable=False, index=True),
    Column("action_type", String(80), nullable=False),
    Column("summary", String(1000), nullable=False),
    Column("risk_context", String(2000), nullable=False),
    Column("status", String(16), nullable=False, index=True),
    Column("created_at", String(40), nullable=False),
    Column("resolved_at", String(40)),
    Column("resolution_note", String(2000)),
)


class ApprovalStore:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def initialize(self) -> None:
        metadata.create_all(self.engine, tables=[missions, approvals])

    def create(self, request: ApprovalCreate) -> Approval:
        record = Approval(
            **request.model_dump(), id=uuid4(), status="PENDING", created_at=datetime.now(UTC)
        )
        with self.engine.begin() as connection:
            mission = connection.execute(
                select(missions.c.id).where(missions.c.id == str(request.mission_id))
            ).first()
            if mission is None:
                raise RecordNotFoundError("Mission not found")
            connection.execute(insert(approvals).values(**record.model_dump(mode="json")))
        return record

    def get(self, approval_id: UUID) -> Approval:
        with self.engine.connect() as connection:
            row = (
                connection.execute(select(approvals).where(approvals.c.id == str(approval_id)))
                .mappings()
                .first()
            )
        if row is None:
            raise RecordNotFoundError("Approval not found")
        return Approval.model_validate(dict(row))

    def list(
        self,
        limit: int = 50,
        offset: int = 0,
        mission_id: UUID | None = None,
    ) -> list[Approval]:
        query = select(approvals)
        if mission_id is not None:
            query = query.where(approvals.c.mission_id == str(mission_id))
        with self.engine.connect() as connection:
            rows = (
                connection.execute(
                    query.order_by(approvals.c.created_at.desc(), approvals.c.id)
                    .limit(min(max(limit, 1), 100))
                    .offset(min(max(offset, 0), 2**63 - 1))
                )
                .mappings()
                .all()
            )
        return [Approval.model_validate(dict(row)) for row in rows]

    def resolve(self, approval_id: UUID, request: ApprovalResolve) -> Approval:
        with self.engine.begin() as connection:
            connection.execute(
                update(approvals)
                .where(
                    approvals.c.id == str(approval_id),
                    approvals.c.status == "PENDING",
                )
                .values(**request.model_dump(), resolved_at=datetime.now(UTC).isoformat())
            )
            row = (
                connection.execute(select(approvals).where(approvals.c.id == str(approval_id)))
                .mappings()
                .first()
            )
            if row is None:
                raise RecordNotFoundError("Approval not found")
            record = Approval.model_validate(dict(row))
            # Existing databases may contain orphan rows (SQLite foreign keys were
            # historically disabled). Never resolve one into a valid decision.
            mission = connection.execute(
                select(missions.c.id).where(missions.c.id == str(record.mission_id))
            ).first()
            if mission is None:
                raise RecordConflictError("Approval mission no longer exists")
            if record.status != request.status or record.resolution_note != request.resolution_note:
                raise RecordConflictError("Approval already resolved with a different decision")
        return record
