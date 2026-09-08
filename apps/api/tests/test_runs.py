import asyncio
import threading
from uuid import uuid4

import pytest

from jarvis_api.assistants import get_assistant
from jarvis_api.conversations import ConversationStore
from jarvis_api.orchestration import AssistantOrchestrator, AssistantResult
from jarvis_api.runs import (
    IllegalRunTransitionError,
    RunConflictError,
    RunExecutor,
    RunExpiredError,
    RunOwnershipError,
    RunState,
    RunStore,
    sse_events,
)
from jarvis_api.tools import ToolError


class StreamingOrchestrator:
    def __init__(self, chunks: tuple[str, ...] = ("Good ", "evening."), delay: float = 0) -> None:
        self.chunks = chunks
        self.delay = delay

    async def respond(self, message, assistant, history, **kwargs):
        for chunk in self.chunks:
            if self.delay:
                await asyncio.sleep(self.delay)
            await kwargs["delta_handler"](chunk)
        return AssistantResult("".join(self.chunks))


class ProjectTools:
    def routing_context(self):
        return {"projects": [{"id": "0123456789abcdef", "name": "ExoHunter"}]}

    def execute(self, call, *, allow_external_actions=False):
        assert call.arguments == {"project_id": "0123456789abcdef"}
        return {"project": {"name": "ExoHunter", "branch": "main", "is_dirty": False}}


class UnusedOllama:
    pass


class PartialFailureOrchestrator:
    async def respond(self, message, assistant, history, **kwargs):
        await kwargs["delta_handler"]("partial")
        raise RuntimeError("malformed upstream stream")


class CancellationResistantOrchestrator:
    def __init__(self) -> None:
        self.first_delta = asyncio.Event()
        self.release = asyncio.Event()

    async def respond(self, message, assistant, history, **kwargs):
        await kwargs["delta_handler"]("partial")
        self.first_delta.set()
        try:
            await self.release.wait()
        except asyncio.CancelledError:
            await kwargs["delta_handler"](" late")
        return AssistantResult("partial late")


class FailingProjectTools(ProjectTools):
    def execute(self, call, *, allow_external_actions=False):
        raise ToolError("invalid tool request")


class SlowProjectTools(ProjectTools):
    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()
        self.executions = 0

    def execute(self, call, *, allow_external_actions=False):
        self.executions += 1
        self.started.set()
        self.release.wait(timeout=1)
        return super().execute(call, allow_external_actions=allow_external_actions)


@pytest.mark.anyio
async def test_run_streams_deltas_and_commits_one_final_turn() -> None:
    conversations = ConversationStore()
    session = conversations.create()
    store = RunStore()
    run = store.create(session.id)
    executor = RunExecutor(
        store,
        conversations,
        StreamingOrchestrator(),  # type: ignore[arg-type]
        get_assistant(),
    )

    await executor.execute(run.id, "Hello")

    snapshot = store.snapshot(run.id, session.id)
    assert snapshot.state == RunState.COMPLETED
    deltas = [
        event.data["content"]
        for event in snapshot.events
        if event.type == "assistant.delta"
    ]
    assert deltas == ["Good ", "evening."]
    assert [event.type for event in snapshot.events].count("run.completed") == 1
    assert conversations.get(session.id).turns[0].assistant == "Good evening."


@pytest.mark.anyio
async def test_cancellation_is_terminal_and_does_not_commit_history() -> None:
    conversations = ConversationStore()
    session = conversations.create()
    store = RunStore()
    run = store.create(session.id)
    executor = RunExecutor(
        store,
        conversations,
        StreamingOrchestrator(("late",), delay=1),  # type: ignore[arg-type]
        get_assistant(),
    )
    task = asyncio.create_task(executor.execute(run.id, "Wait"))
    store.attach_task(run.id, task)
    await asyncio.sleep(0)

    store.request_cancel(run.id, session.id)
    await task

    snapshot = store.snapshot(run.id, session.id)
    assert snapshot.state == RunState.CANCELLED
    assert not conversations.get(session.id).turns
    assert not any(event.type == "run.completed" for event in snapshot.events)
    assert store.request_cancel(run.id, session.id).state == RunState.CANCELLED


@pytest.mark.anyio
async def test_cancellation_resistant_model_cannot_emit_or_commit_late_output() -> None:
    conversations = ConversationStore()
    session = conversations.create()
    store = RunStore()
    run = store.create(session.id)
    orchestrator = CancellationResistantOrchestrator()
    executor = RunExecutor(
        store,
        conversations,
        orchestrator,  # type: ignore[arg-type]
        get_assistant(),
    )
    task = asyncio.create_task(executor.execute(run.id, "Wait"))
    store.attach_task(run.id, task)
    await orchestrator.first_delta.wait()

    store.request_cancel(run.id, session.id)
    await task

    snapshot = store.snapshot(run.id)
    assert snapshot.state == RunState.CANCELLED
    deltas = [
        event.data["content"]
        for event in snapshot.events
        if event.type == "assistant.delta"
    ]
    assert deltas == ["partial"]
    assert not conversations.get(session.id).turns
    assert not any(event.type == "run.completed" for event in snapshot.events)


@pytest.mark.anyio
async def test_overall_timeout_is_terminal() -> None:
    conversations = ConversationStore()
    session = conversations.create()
    store = RunStore()
    run = store.create(session.id)
    executor = RunExecutor(
        store,
        conversations,
        StreamingOrchestrator(("late",), delay=1),  # type: ignore[arg-type]
        get_assistant(),
        timeout_seconds=0.01,
    )

    await executor.execute(run.id, "Wait")

    assert store.snapshot(run.id).state == RunState.TIMED_OUT
    assert not conversations.get(session.id).turns
    assert store.create(session.id).state == RunState.QUEUED


@pytest.mark.anyio
async def test_timeout_wins_even_when_upstream_swallows_cancellation() -> None:
    conversations = ConversationStore()
    session = conversations.create()
    store = RunStore()
    run = store.create(session.id)
    orchestrator = CancellationResistantOrchestrator()
    executor = RunExecutor(
        store,
        conversations,
        orchestrator,  # type: ignore[arg-type]
        get_assistant(),
        timeout_seconds=0.01,
    )

    await executor.execute(run.id, "Wait")
    await asyncio.sleep(0)

    snapshot = store.snapshot(run.id)
    assert snapshot.state == RunState.TIMED_OUT
    deltas = [
        event.data["content"]
        for event in snapshot.events
        if event.type == "assistant.delta"
    ]
    assert deltas == ["partial"]
    assert not conversations.get(session.id).turns


@pytest.mark.anyio
async def test_validated_project_tool_emits_progress_before_grounded_delta() -> None:
    conversations = ConversationStore()
    session = conversations.create()
    store = RunStore()
    run = store.create(session.id)
    orchestrator = AssistantOrchestrator(UnusedOllama(), ProjectTools())  # type: ignore[arg-type]
    executor = RunExecutor(store, conversations, orchestrator, get_assistant())

    await executor.execute(run.id, "What branch is ExoHunter on?")

    events = store.snapshot(run.id).events
    types = [event.type for event in events]
    assert types.index("tool.requested") < types.index("tool.started")
    assert types.index("tool.completed") < types.index("assistant.delta")
    assert events[types.index("assistant.delta")].data["content"] == "ExoHunter is on branch main."


@pytest.mark.anyio
async def test_partial_failure_is_failed_and_never_committed() -> None:
    conversations = ConversationStore()
    session = conversations.create()
    store = RunStore()
    run = store.create(session.id)
    executor = RunExecutor(
        store,
        conversations,
        PartialFailureOrchestrator(),  # type: ignore[arg-type]
        get_assistant(),
    )

    await executor.execute(run.id, "Hello")

    events = store.snapshot(run.id).events
    assert [event.type for event in events][-1] == "run.failed"
    assert any(event.type == "assistant.delta" for event in events)
    assert not conversations.get(session.id).turns


@pytest.mark.anyio
async def test_invalid_tool_emits_failed_event_and_preserves_validation() -> None:
    conversations = ConversationStore()
    session = conversations.create()
    store = RunStore()
    run = store.create(session.id)
    orchestrator = AssistantOrchestrator(
        UnusedOllama(), FailingProjectTools()  # type: ignore[arg-type]
    )
    executor = RunExecutor(store, conversations, orchestrator, get_assistant())

    await executor.execute(run.id, "What branch is ExoHunter on?")

    types = [event.type for event in store.snapshot(run.id).events]
    assert "tool.failed" in types
    assert types[-1] == "run.failed"
    assert not conversations.get(session.id).turns


@pytest.mark.anyio
async def test_slow_tool_result_cannot_resurrect_cancelled_run() -> None:
    conversations = ConversationStore()
    session = conversations.create()
    store = RunStore()
    run = store.create(session.id)
    tools = SlowProjectTools()
    orchestrator = AssistantOrchestrator(UnusedOllama(), tools)  # type: ignore[arg-type]
    executor = RunExecutor(store, conversations, orchestrator, get_assistant())
    task = asyncio.create_task(executor.execute(run.id, "What branch is ExoHunter on?"))
    store.attach_task(run.id, task)
    await asyncio.to_thread(tools.started.wait, 1)

    store.request_cancel(run.id, session.id)
    tools.release.set()
    await task
    await asyncio.sleep(0.01)

    snapshot = store.snapshot(run.id)
    assert tools.executions == 1
    assert snapshot.state == RunState.CANCELLED
    assert not any(event.type in {"tool.completed", "run.completed"} for event in snapshot.events)
    assert not conversations.get(session.id).turns


@pytest.mark.anyio
async def test_tool_timeout_is_timed_out_and_releases_conversation() -> None:
    conversations = ConversationStore()
    session = conversations.create()
    store = RunStore()
    run = store.create(session.id)
    tools = SlowProjectTools()
    orchestrator = AssistantOrchestrator(UnusedOllama(), tools)  # type: ignore[arg-type]
    executor = RunExecutor(
        store,
        conversations,
        orchestrator,
        get_assistant(),
        tool_timeout_seconds=0.01,
    )

    await executor.execute(run.id, "What branch is ExoHunter on?")
    tools.release.set()

    snapshot = store.snapshot(run.id)
    assert snapshot.state == RunState.TIMED_OUT
    assert "tool.failed" in [event.type for event in snapshot.events]
    assert not conversations.get(session.id).turns
    assert store.create(session.id).state == RunState.QUEUED


def test_state_machine_rejects_illegal_transitions_and_concurrent_run() -> None:
    conversation_id = uuid4()
    store = RunStore()
    run = store.create(conversation_id)
    with pytest.raises(RunConflictError):
        store.create(conversation_id)
    with pytest.raises(IllegalRunTransitionError):
        store.transition(run.id, RunState.COMPLETED, "run.completed")
    other = store.create(uuid4())
    assert other.state == RunState.QUEUED
    store.transition(run.id, RunState.RUNNING, "run.started")
    store.transition(run.id, RunState.COMPLETED, "run.completed")
    with pytest.raises(IllegalRunTransitionError):
        store.transition(run.id, RunState.FAILED, "run.failed")


def test_run_ownership_is_enforced() -> None:
    store = RunStore()
    run = store.create(uuid4())
    with pytest.raises(RunOwnershipError):
        store.snapshot(run.id, uuid4())


def test_immediate_pre_start_cancellation_is_not_left_cancelling() -> None:
    conversation_id = uuid4()
    store = RunStore()
    run = store.create(conversation_id)

    cancelled = store.request_cancel(run.id, conversation_id)

    assert cancelled.state == RunState.CANCELLED
    assert [event.type for event in cancelled.events][-2:] == [
        "run.cancelling",
        "run.cancelled",
    ]
    assert store.request_cancel(run.id, conversation_id).state == RunState.CANCELLED


def test_terminal_run_expires_and_events_are_bounded() -> None:
    now = 0.0

    def clock() -> float:
        return now

    store = RunStore(terminal_ttl_seconds=1, max_events_per_run=10, clock=clock)
    run = store.create(uuid4())
    store.transition(run.id, RunState.RUNNING, "run.started")
    for index in range(20):
        store.append_event(run.id, "assistant.delta", {"content": str(index)})
    assert len(store.snapshot(run.id).events) == 10
    store.transition(run.id, RunState.COMPLETED, "run.completed")
    now = 2
    with pytest.raises(RunExpiredError):
        store.snapshot(run.id)


def test_run_limit_evicts_old_terminal_but_never_active_run() -> None:
    store = RunStore(max_runs=2)
    old = store.create(uuid4())
    store.transition(old.id, RunState.RUNNING, "run.started")
    store.transition(old.id, RunState.COMPLETED, "run.completed")
    active = store.create(uuid4())

    replacement = store.create(uuid4())

    with pytest.raises(RunExpiredError):
        store.snapshot(old.id)
    assert store.snapshot(active.id).state == RunState.QUEUED
    assert store.snapshot(replacement.id).state == RunState.QUEUED


@pytest.mark.parametrize(
    "terminal",
    [RunState.COMPLETED, RunState.FAILED, RunState.CANCELLED, RunState.TIMED_OUT],
)
def test_every_terminal_state_rejects_post_terminal_mutation(terminal: RunState) -> None:
    store = RunStore()
    run = store.create(uuid4())
    if terminal == RunState.CANCELLED:
        store.transition(run.id, RunState.CANCELLING, "run.cancelling")
    else:
        store.transition(run.id, RunState.RUNNING, "run.started")
    store.transition(run.id, terminal, f"run.{terminal.value.casefold()}")

    with pytest.raises(IllegalRunTransitionError):
        store.transition(run.id, RunState.RUNNING, "run.started")
    assert store.snapshot(run.id).state == terminal


@pytest.mark.anyio
async def test_sse_supports_cursor_without_replaying_prior_events() -> None:
    conversation_id = uuid4()
    store = RunStore()
    run = store.create(conversation_id)
    store.transition(run.id, RunState.RUNNING, "run.started")
    store.transition(run.id, RunState.COMPLETED, "run.completed")

    frames = [frame async for frame in sse_events(store, run.id, conversation_id, after=1)]

    assert "run.created" not in "".join(frames)
    assert "run.started" in frames[0]
    assert "run.completed" in frames[1]


@pytest.mark.anyio
async def test_sse_sanitizes_non_serializable_internal_event_and_closes() -> None:
    conversation_id = uuid4()
    store = RunStore()
    run = store.create(conversation_id)
    store.transition(run.id, RunState.RUNNING, "run.started")
    store.append_event(run.id, "assistant.delta", {"content": object()})
    store.transition(run.id, RunState.COMPLETED, "run.completed")

    frames = [frame async for frame in sse_events(store, run.id, conversation_id)]

    assert "Event payload unavailable." in "".join(frames)
    assert "run.completed" in frames[-1]
    assert "object at" not in "".join(frames)


@pytest.mark.anyio
async def test_detached_and_reconnected_stream_never_duplicates_history() -> None:
    conversations = ConversationStore()
    session = conversations.create()
    store = RunStore()
    run = store.create(session.id)
    executor = RunExecutor(
        store,
        conversations,
        StreamingOrchestrator(("Detached response.",)),  # type: ignore[arg-type]
        get_assistant(),
    )

    await executor.execute(run.id, "Hello")
    first = [frame async for frame in sse_events(store, run.id, session.id)]
    second = [frame async for frame in sse_events(store, run.id, session.id)]

    assert "run.completed" in first[-1]
    assert "run.completed" in second[-1]
    assert len(conversations.get(session.id).turns) == 1
