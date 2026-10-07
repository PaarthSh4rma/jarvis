from concurrent.futures import ThreadPoolExecutor
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, text
from sqlalchemy.exc import IntegrityError

from jarvis_api.approvals import ApprovalCreate, ApprovalResolve, ApprovalStore
from jarvis_api.database import create_database_engine
from jarvis_api.integrations.hermes import HermesAdapter
from jarvis_api.main import app, get_ollama_service, get_project_service
from jarvis_api.missions import (
    MissionCreate,
    MissionPatch,
    MissionStore,
    RecordConflictError,
    RecordNotFoundError,
)
from jarvis_api.missions import (
    missions as mission_table,
)


@pytest.fixture
def stores(tmp_path):
    engine = create_database_engine(f"sqlite:///{tmp_path / 'foundation.db'}")
    missions = MissionStore(engine)
    approvals = ApprovalStore(engine)
    approvals.initialize()
    yield missions, approvals, engine
    engine.dispose()


@pytest.fixture
def client(stores, monkeypatch):
    missions, approvals, _ = stores
    monkeypatch.setattr(app.state, "missions", missions)
    monkeypatch.setattr(app.state, "approvals", approvals)

    def forbidden():
        raise AssertionError("Foundation must not depend on model or project discovery")

    app.dependency_overrides[get_ollama_service] = forbidden
    app.dependency_overrides[get_project_service] = forbidden
    try:
        # Stores above are initialized against the isolated test database.
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_ollama_service)
        app.dependency_overrides.pop(get_project_service)


def create_mission(store):
    return store.create(MissionCreate(type="PROJECT_REVIEW", title="Review", goal="Inspect only"))


def test_mission_crud_and_persistence(client, stores):
    response = client.post(
        "/missions",
        json={
            "type": "RESEARCH",
            "title": "Research",
            "goal": "Prepare local research",
        },
    )
    assert response.status_code == 201
    record = response.json()
    assert record["status"] == "DRAFT"
    assert record["external_execution_id"] is None
    assert client.get("/missions").json() == [record]
    assert client.get(f"/missions/{record['id']}").json() == record
    response = client.patch(
        f"/missions/{record['id']}",
        json={
            "status": "READY",
            "title": "Reviewed goal",
            "expected_revision": 1,
        },
    )
    assert response.status_code == 200
    assert response.json()["revision"] == 2
    # New engine/store, same on-disk DB: not merely a reused object cache.
    fresh_engine = create_engine(stores[2].url)
    try:
        fresh = MissionStore(fresh_engine)
        fresh.initialize()
        assert fresh.get(UUID(record["id"])).title == "Reviewed goal"
        assert len(fresh.list()) == 1
    finally:
        fresh_engine.dispose()


def test_stale_and_terminal_mission_updates_rejected(client, stores):
    record = create_mission(stores[0])
    path = f"/missions/{record.id}"
    assert client.patch(path, json={"expected_revision": 1, "status": "READY"}).status_code == 200
    assert client.patch(path, json={"expected_revision": 1, "title": "stale"}).status_code == 409
    assert (
        client.patch(path, json={"expected_revision": 2, "status": "CANCELLED"}).status_code == 200
    )
    assert client.patch(path, json={"expected_revision": 3, "status": "READY"}).status_code == 409


@pytest.mark.parametrize(
    "extra",
    [
        {"unexpected": True},
        {"status": "RUNNING"},
        {"external_execution_id": "fake"},
        {"result_summary": "forged"},
        {"failure_summary": "forged"},
    ],
)
def test_unknown_or_execution_create_fields_rejected(client, extra):
    assert (
        client.post(
            "/missions",
            json={
                "type": "ADMIN",
                "title": "Test",
                "goal": "Test",
                **extra,
            },
        ).status_code
        == 422
    )


@pytest.mark.parametrize(
    "change",
    [
        {"unexpected": True},
        {"status": "RUNNING"},
        {"goal": None},
        {},
        {"title": " "},
        {"external_execution_id": "fake"},
        {"result_summary": "forged"},
        {"failure_summary": "forged"},
        {"status": "COMPLETED"},
        {"status": "WAITING_FOR_APPROVAL"},
    ],
)
def test_invalid_patches(client, stores, change):
    record = create_mission(stores[0])
    assert (
        client.patch(
            f"/missions/{record.id}",
            json={
                "expected_revision": 1,
                **change,
            },
        ).status_code
        == 422
    )


def test_bounded_lists_and_not_found(client):
    assert client.get("/missions?limit=101").status_code == 422
    assert client.get("/approvals?offset=-1").status_code == 422
    assert client.get(f"/missions/{uuid4()}").status_code == 404
    assert client.get(f"/approvals/{uuid4()}").status_code == 404
    assert client.get("/missions/not-a-uuid").status_code == 422
    assert client.get("/approvals/not-a-uuid").status_code == 422
    assert (
        client.post("/approvals/not-a-uuid/resolve", json={"status": "APPROVED"}).status_code == 422
    )


def test_approval_resolves_persists_and_never_dispatches(client, stores, monkeypatch):
    missions, approvals, engine = stores
    mission = create_mission(missions)
    approval = approvals.create(
        ApprovalCreate(
            mission_id=mission.id,
            action_type="WORKSPACE_EDIT",
            summary="Proposed edit",
            risk_context="Human decision record only",
        )
    )

    def forbidden(*args, **kwargs):
        raise AssertionError("Approval must not perform network or tool actions")

    monkeypatch.setattr(httpx.AsyncClient, "send", forbidden)
    from jarvis_api.tools import ToolRegistry

    monkeypatch.setattr(ToolRegistry, "execute", forbidden)
    assert client.get("/approvals").json()[0]["status"] == "PENDING"
    assert client.get(f"/approvals?mission_id={uuid4()}").json() == []
    path = f"/approvals/{approval.id}/resolve"
    decision = {"status": "APPROVED", "resolution_note": "Reviewed locally"}
    first = client.post(path, json=decision)
    assert first.status_code == 200
    assert first.json()["resolved_at"] is not None
    assert client.post(path, json=decision).json() == first.json()
    assert client.post(path, json={"status": "REJECTED"}).status_code == 409
    assert client.get(f"/approvals/{approval.id}").json() == first.json()
    assert missions.get(mission.id) == mission
    fresh_engine = create_engine(engine.url)
    try:
        fresh = ApprovalStore(fresh_engine)
        fresh.initialize()
        assert fresh.get(approval.id).status == "APPROVED"
    finally:
        fresh_engine.dispose()


def test_approval_validation_and_internal_creation_only(client, stores):
    with pytest.raises(RecordNotFoundError):
        stores[1].create(
            ApprovalCreate(
                mission_id=uuid4(),
                action_type="EDIT",
                summary="Edit",
                risk_context="Review",
            )
        )
    assert client.post("/approvals", json={}).status_code == 405
    assert (
        client.post(f"/approvals/{uuid4()}/resolve", json={"status": "PENDING"}).status_code == 422
    )
    assert (
        client.post(
            f"/approvals/{uuid4()}/resolve",
            json={
                "status": "APPROVED",
                "execute": True,
            },
        ).status_code
        == 422
    )
    assert (
        client.post(f"/approvals/{uuid4()}/resolve", json={"status": "REJECTED"}).status_code == 404
    )


def test_concurrent_decisions_have_one_winner(stores):
    mission = create_mission(stores[0])
    approval = stores[1].create(
        ApprovalCreate(
            mission_id=mission.id,
            action_type="EDIT",
            summary="Edit",
            risk_context="Review",
        )
    )

    def decide(status):
        try:
            return (
                ApprovalStore(stores[2]).resolve(approval.id, ApprovalResolve(status=status)).status
            )
        except RecordConflictError:
            return "CONFLICT"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(decide, ["APPROVED", "REJECTED"]))
    assert results.count("CONFLICT") == 1
    assert stores[1].get(approval.id).status in {"APPROVED", "REJECTED"}


def test_concurrent_mission_edits_have_one_winner(stores):
    mission = create_mission(stores[0])

    def edit(title):
        try:
            return (
                MissionStore(stores[2])
                .update(mission.id, MissionPatch(expected_revision=1, title=title))
                .title
            )
        except RecordConflictError:
            return "CONFLICT"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(edit, ["First", "Second"]))
    assert results.count("CONFLICT") == 1


def test_hermes_routes_do_not_need_ollama_or_projects(client, monkeypatch):
    def respond(request):
        if request.url.path == "/health":
            return httpx.Response(
                200,
                json={
                    "status": "ok",
                    "platform": "hermes-agent",
                    "version": "dev",
                },
            )
        return httpx.Response(401)

    monkeypatch.setattr(app.state, "hermes", HermesAdapter(transport=httpx.MockTransport(respond)))
    assert client.get("/integrations/hermes/health").json()["state"] == "ONLINE"
    assert client.get("/integrations/hermes/capabilities").json()["state"] == "UNKNOWN"


def test_worker_contracts_have_no_execution_authority():
    from pydantic import ValidationError

    from jarvis_api.agents import AgentTask

    task = AgentTask(mission_id=uuid4(), agent="CODEX", goal="Inspect")
    assert task.permission_scope == "READ_ONLY"
    with pytest.raises(ValidationError):
        AgentTask(mission_id=uuid4(), agent="CLAUDE", goal="Review", execute=True)


def test_approval_creation_contract_is_strict():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ApprovalCreate(
            mission_id=uuid4(),
            action_type="EDIT",
            summary="Edit",
            risk_context="Review",
            execute=True,
        )


def test_project_reference_is_validated_only_when_supplied(client, monkeypatch):
    from jarvis_api.projects import ProjectNotFoundError

    class Projects:
        def get(self, project_id):
            raise ProjectNotFoundError(project_id)

    monkeypatch.setattr(app.state, "mission_projects", Projects())
    assert (
        client.post(
            "/missions",
            json={
                "type": "ADMIN",
                "title": "Test",
                "goal": "Local only",
                "project_id": "0123456789abcdef",
            },
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/missions",
            json={
                "type": "ADMIN",
                "title": "Test",
                "goal": "Local only",
            },
        ).status_code
        == 201
    )


@pytest.mark.parametrize("ollama_online", [False, True])
def test_hermes_offline_does_not_break_jarvis_health(client, monkeypatch, ollama_online):
    class Ollama:
        model = "test"

        async def is_available(self):
            return ollama_online

    def offline(request):
        raise httpx.ConnectError("offline", request=request)

    app.dependency_overrides[get_ollama_service] = lambda: Ollama()
    monkeypatch.setattr(app.state, "hermes", HermesAdapter(transport=httpx.MockTransport(offline)))
    assert client.get("/integrations/hermes/health").json()["state"] == "OFFLINE"
    assert client.get("/health").json()["status"] == "ok"


def test_huge_sqlite_integers_are_rejected_before_binding(client, stores):
    mission = create_mission(stores[0])
    assert (
        client.patch(
            f"/missions/{mission.id}",
            json={
                "expected_revision": 10**100,
                "title": "Invalid revision",
            },
        ).status_code
        == 422
    )
    for route in ("missions", "approvals"):
        assert client.get(f"/{route}?offset={10**100}").status_code == 422
        assert client.get(f"/{route}?offset={2**63 - 1}").status_code == 200
    assert stores[0].get(mission.id) == mission


def test_foreign_keys_enforced_on_each_connection(stores):
    mission = create_mission(stores[0])
    stores[1].create(
        ApprovalCreate(
            mission_id=mission.id,
            action_type="EDIT",
            summary="Edit",
            risk_context="Review",
        )
    )
    # Keep two connections open to exercise multiple physical pooled connections.
    with stores[2].connect() as first, stores[2].connect() as second:
        assert first.scalar(text("PRAGMA foreign_keys")) == 1
        assert second.scalar(text("PRAGMA foreign_keys")) == 1
    with pytest.raises(IntegrityError), stores[2].begin() as connection:
        connection.execute(delete(mission_table).where(mission_table.c.id == str(mission.id)))
    assert stores[0].get(mission.id) == mission


def test_legacy_orphan_cannot_be_resolved_and_mutation_rolls_back(stores):
    mission = create_mission(stores[0])
    approval = stores[1].create(
        ApprovalCreate(
            mission_id=mission.id,
            action_type="EDIT",
            summary="Edit",
            risk_context="Review",
        )
    )
    # Simulate a pre-hardening/external connection that did not enforce foreign keys.
    legacy_engine = create_engine(stores[2].url)
    with legacy_engine.begin() as connection:
        connection.execute(delete(mission_table).where(mission_table.c.id == str(mission.id)))
    legacy_engine.dispose()
    with pytest.raises(RecordConflictError, match="mission no longer exists"):
        stores[1].resolve(approval.id, ApprovalResolve(status="APPROVED"))
    assert stores[1].get(approval.id) == approval
    with pytest.raises(RecordNotFoundError):
        stores[1].create(
            ApprovalCreate(
                mission_id=mission.id,
                action_type="EDIT",
                summary="Edit",
                risk_context="Review",
            )
        )
