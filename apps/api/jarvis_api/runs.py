import asyncio
import json
import logging
import threading
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from jarvis_api.assistants import Assistant
from jarvis_api.conversations import ConversationStore
from jarvis_api.orchestration import AssistantOrchestrator

logger = logging.getLogger(__name__)


class RunState(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    WAITING_FOR_TOOL = "WAITING_FOR_TOOL"
    CANCELLING = "CANCELLING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    TIMED_OUT = "TIMED_OUT"


TERMINAL_STATES = {RunState.COMPLETED, RunState.FAILED, RunState.CANCELLED, RunState.TIMED_OUT}
ALLOWED_TRANSITIONS = {
    RunState.QUEUED: {RunState.RUNNING, RunState.CANCELLING, RunState.CANCELLED},
    RunState.RUNNING: {
        RunState.WAITING_FOR_TOOL,
        RunState.CANCELLING,
        RunState.COMPLETED,
        RunState.FAILED,
        RunState.TIMED_OUT,
    },
    RunState.WAITING_FOR_TOOL: {
        RunState.RUNNING,
        RunState.CANCELLING,
        RunState.FAILED,
        RunState.TIMED_OUT,
    },
    RunState.CANCELLING: {RunState.CANCELLED},
    RunState.COMPLETED: set(),
    RunState.FAILED: set(),
    RunState.CANCELLED: set(),
    RunState.TIMED_OUT: set(),
}


class RunError(RuntimeError):
    pass


class RunNotFoundError(RunError):
    pass


class RunExpiredError(RunError):
    pass


class RunConflictError(RunError):
    pass


class RunOwnershipError(RunError):
    pass


class IllegalRunTransitionError(RunError):
    pass


@dataclass(frozen=True)
class RunEvent:
    sequence: int
    type: str
    timestamp: datetime
    data: dict[str, object] = field(default_factory=dict)


@dataclass
class Run:
    id: UUID
    conversation_id: UUID
    state: RunState
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    events: list[RunEvent] = field(default_factory=list)


class RunStore:
    def __init__(
        self,
        *,
        max_runs: int = 100,
        terminal_ttl_seconds: int = 900,
        max_events_per_run: int = 200,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.max_runs = max_runs
        self.terminal_ttl_seconds = terminal_ttl_seconds
        self.max_events_per_run = max_events_per_run
        self._clock = clock
        self._runs: dict[UUID, Run] = {}
        self._created_monotonic: dict[UUID, float] = {}
        self._terminal_monotonic: dict[UUID, float] = {}
        self._expired: list[UUID] = []
        self._active_by_conversation: dict[UUID, UUID] = {}
        self._tasks: dict[UUID, asyncio.Task[None]] = {}
        self._lock = threading.RLock()

    def create(self, conversation_id: UUID) -> Run:
        with self._lock:
            self._cleanup()
            if conversation_id in self._active_by_conversation:
                raise RunConflictError("A run is already active for this conversation.")
            if len(self._runs) >= self.max_runs:
                self._evict_oldest_terminal()
            if len(self._runs) >= self.max_runs:
                raise RunConflictError("The local run limit has been reached.")
            now = datetime.now(UTC)
            run = Run(uuid4(), conversation_id, RunState.QUEUED, now)
            self._runs[run.id] = run
            self._created_monotonic[run.id] = self._clock()
            self._active_by_conversation[conversation_id] = run.id
            self.append_event(run.id, "run.created", {"state": run.state})
            return self.snapshot(run.id)

    def attach_task(self, run_id: UUID, task: asyncio.Task[None]) -> None:
        with self._lock:
            self._tasks[run_id] = task

    def transition(
        self,
        run_id: UUID,
        state: RunState,
        event_type: str,
        data: dict[str, object] | None = None,
    ) -> Run:
        with self._lock:
            run = self._get(run_id)
            if state not in ALLOWED_TRANSITIONS[run.state]:
                raise IllegalRunTransitionError(f"Illegal transition: {run.state} -> {state}")
            run.state = state
            now = datetime.now(UTC)
            if state == RunState.RUNNING and run.started_at is None:
                run.started_at = now
            if state in TERMINAL_STATES:
                run.completed_at = now
                self._terminal_monotonic[run.id] = self._clock()
                self._active_by_conversation.pop(run.conversation_id, None)
                self._tasks.pop(run.id, None)
            self.append_event(run_id, event_type, {"state": state, **(data or {})})
            logger.info("run_transition run_id=%s state=%s event=%s", run_id, state, event_type)
            return self.snapshot(run_id)

    def append_event(self, run_id: UUID, event_type: str, data: dict[str, object]) -> RunEvent:
        with self._lock:
            run = self._get(run_id)
            sequence = run.events[-1].sequence + 1 if run.events else 1
            event = RunEvent(sequence, event_type, datetime.now(UTC), data)
            run.events.append(event)
            if len(run.events) > self.max_events_per_run:
                run.events.pop(0)
            return event

    def snapshot(self, run_id: UUID, conversation_id: UUID | None = None) -> Run:
        with self._lock:
            run = self._get(run_id)
            if conversation_id is not None and run.conversation_id != conversation_id:
                raise RunOwnershipError("Run does not belong to this conversation.")
            return Run(
                id=run.id,
                conversation_id=run.conversation_id,
                state=run.state,
                created_at=run.created_at,
                started_at=run.started_at,
                completed_at=run.completed_at,
                events=list(run.events),
            )

    def events_after(
        self, run_id: UUID, sequence: int, conversation_id: UUID
    ) -> tuple[RunEvent, ...]:
        run = self.snapshot(run_id, conversation_id)
        return tuple(event for event in run.events if event.sequence > sequence)

    def request_cancel(self, run_id: UUID, conversation_id: UUID) -> Run:
        with self._lock:
            run = self._get(run_id)
            if run.conversation_id != conversation_id:
                raise RunOwnershipError("Run does not belong to this conversation.")
            if run.state in TERMINAL_STATES or run.state == RunState.CANCELLING:
                return self.snapshot(run_id)
            self.transition(run_id, RunState.CANCELLING, "run.cancelling")
            task = self._tasks.get(run_id)
            if task is not None:
                task.cancel()
            self.transition(run_id, RunState.CANCELLED, "run.cancelled")
            return self.snapshot(run_id)

    def _get(self, run_id: UUID) -> Run:
        self._cleanup()
        run = self._runs.get(run_id)
        if run is not None:
            return run
        if run_id in self._expired:
            raise RunExpiredError(str(run_id))
        raise RunNotFoundError(str(run_id))

    def _cleanup(self) -> None:
        now = self._clock()
        expired = [
            run_id
            for run_id, ended in self._terminal_monotonic.items()
            if now - ended > self.terminal_ttl_seconds
        ]
        for run_id in expired:
            self._remove(run_id)

    def _evict_oldest_terminal(self) -> None:
        if not self._terminal_monotonic:
            return
        self._remove(min(self._terminal_monotonic, key=self._terminal_monotonic.get))

    def _remove(self, run_id: UUID) -> None:
        run = self._runs.pop(run_id, None)
        if run is None:
            return
        self._active_by_conversation.pop(run.conversation_id, None)
        self._created_monotonic.pop(run_id, None)
        self._terminal_monotonic.pop(run_id, None)
        self._tasks.pop(run_id, None)
        self._expired.append(run_id)
        if len(self._expired) > self.max_runs:
            self._expired.pop(0)


class RunExecutor:
    def __init__(
        self,
        store: RunStore,
        conversations: ConversationStore,
        orchestrator: AssistantOrchestrator,
        assistant: Assistant,
        *,
        timeout_seconds: float = 90,
        tool_timeout_seconds: float = 15,
    ) -> None:
        self.store = store
        self.conversations = conversations
        self.orchestrator = orchestrator
        self.assistant = assistant
        self.timeout_seconds = timeout_seconds
        self.tool_timeout_seconds = tool_timeout_seconds

    async def execute(self, run_id: UUID, message: str) -> None:
        run = self.store.snapshot(run_id)
        response_task: asyncio.Task | None = None
        try:
            if run.state == RunState.CANCELLING:
                self.store.transition(run_id, RunState.CANCELLED, "run.cancelled")
                return
            self.store.transition(run_id, RunState.RUNNING, "run.started")
            session = self.conversations.get(run.conversation_id)
            emitted_delta = False

            async def delta(content: str) -> None:
                nonlocal emitted_delta
                if self.store.snapshot(run_id).state != RunState.RUNNING:
                    return
                emitted_delta = True
                self.store.append_event(run_id, "assistant.delta", {"content": content})

            def progress(event_type: str, tool_name: str, message_text: str) -> None:
                current = self.store.snapshot(run_id)
                if current.state in TERMINAL_STATES or current.state == RunState.CANCELLING:
                    return
                if event_type == "tool.requested":
                    self.store.transition(
                        run_id,
                        RunState.WAITING_FOR_TOOL,
                        event_type,
                        {"tool": tool_name, "message": message_text},
                    )
                else:
                    self.store.append_event(
                        run_id, event_type, {"tool": tool_name, "message": message_text}
                    )
                if event_type in {"tool.completed", "tool.failed"}:
                    current = self.store.snapshot(run_id)
                    if current.state == RunState.WAITING_FOR_TOOL:
                        self.store.transition(run_id, RunState.RUNNING, "run.resumed")

            response_task = asyncio.create_task(
                self.orchestrator.respond(
                    message,
                    self.assistant,
                    tuple(session.turns),
                    delta_handler=delta,
                    progress_handler=progress,
                    tool_timeout_seconds=self.tool_timeout_seconds,
                    raise_tool_errors=True,
                )
            )
            done, _ = await asyncio.wait({response_task}, timeout=self.timeout_seconds)
            if not done:
                response_task.cancel()
                self.store.transition(run_id, RunState.TIMED_OUT, "run.timed_out")
                return
            result = response_task.result()
            if not emitted_delta and self.store.snapshot(run_id).state == RunState.RUNNING:
                await delta(result.text)
            current = self.store.snapshot(run_id)
            if current.state in {RunState.CANCELLING, RunState.CANCELLED}:
                if current.state == RunState.CANCELLING:
                    self.store.transition(run_id, RunState.CANCELLED, "run.cancelled")
                return
            self.conversations.append(
                run.conversation_id,
                user=message,
                assistant=result.text,
                tool_observation=result.tool_observation,
            )
            self.store.transition(run_id, RunState.COMPLETED, "run.completed")
        except asyncio.CancelledError:
            if response_task is not None and not response_task.done():
                response_task.cancel()
            current = self.store.snapshot(run_id)
            if current.state not in TERMINAL_STATES and current.state != RunState.CANCELLING:
                self.store.transition(run_id, RunState.CANCELLING, "run.cancelling")
                current = self.store.snapshot(run_id)
            if current.state == RunState.CANCELLING:
                self.store.transition(run_id, RunState.CANCELLED, "run.cancelled")
        except TimeoutError:
            current = self.store.snapshot(run_id)
            if current.state not in TERMINAL_STATES and current.state != RunState.CANCELLING:
                self.store.transition(run_id, RunState.TIMED_OUT, "run.timed_out")
        except Exception as error:
            current = self.store.snapshot(run_id)
            if current.state not in TERMINAL_STATES and current.state != RunState.CANCELLING:
                self.store.transition(
                    run_id,
                    RunState.FAILED,
                    "run.failed",
                    {"message": "Execution failed safely."},
                )
            logger.warning("run_failed run_id=%s error_type=%s", run_id, type(error).__name__)


async def sse_events(
    store: RunStore,
    run_id: UUID,
    conversation_id: UUID,
    after: int = 0,
) -> AsyncIterator[str]:
    cursor = after
    while True:
        events = store.events_after(run_id, cursor, conversation_id)
        for event in events:
            cursor = event.sequence
            event_payload = {
                "sequence": event.sequence,
                "type": event.type,
                "timestamp": event.timestamp.isoformat(),
                "data": event.data,
            }
            try:
                payload = json.dumps(event_payload)
            except (TypeError, ValueError):
                event_payload["data"] = {"message": "Event payload unavailable."}
                payload = json.dumps(event_payload)
            yield f"id: {event.sequence}\nevent: {event.type}\ndata: {payload}\n\n"
        if store.snapshot(run_id, conversation_id).state in TERMINAL_STATES:
            break
        await asyncio.sleep(0.05)
