"""Runner + RunContext: the only place events are stamped, tools are executed and totals computed.

Backends translate their native stream into `AgentEvent`s via `ctx.emit` and execute every
tool call via `ctx.execute_tool`. Everything else — envelope, output, usage totals, subagent
delegation, tool validation / timeout / clipping — happens here, once, for all backends.
"""

import asyncio
import json
import logging
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Coroutine, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

import anyio
from pydantic import BaseModel, ValidationError

from agent_core.context import DelegateInput, clip, delegate_description
from agent_core.events import (
    AgentEvent,
    RunCompleted,
    RunFailed,
    RunStarted,
    StopReason,
    SubagentCompleted,
    SubagentStarted,
    TextDelta,
    ToolCall,
    ToolResult,
    TurnCompleted,
    TurnStarted,
    child_agent_path,
)
from agent_core.observe import Observer
from agent_core.spec import AgentSpec
from agent_core.tools import ToolSpec, delegate_tool_name

logger = logging.getLogger("agent_core.runtime")

Sink = Callable[[AgentEvent], Awaitable[None]]
# Time a cancelled run gets to shut its backend down (CLI process, server interrupt, streams).
# Agent SDK needs ~5s per CLI level (MCP bridge grace + graceful exit), nested delegations more.
CLEANUP_TIMEOUT_S = 30.0
SessionState = dict[str, Any]


class BackendError(Exception):
    """Failure a client may see. `message` must not contain internal details."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


@dataclass(frozen=True)
class BackendResult:
    stop_reason: StopReason
    state: SessionState | None
    """Backend-specific JSON needed to continue the session next run (None = nothing to keep)."""


class Backend(Protocol):
    name: str

    async def run(
        self, ctx: RunContext, prompt: str, state: SessionState | None
    ) -> BackendResult: ...


class SessionStore(Protocol):
    async def load_state(self, session_id: str) -> SessionState | None: ...

    async def save_state(self, session_id: str, state: SessionState | None) -> None: ...


@dataclass(frozen=True)
class ToolOutcome:
    content: str
    is_error: bool


class RunContext:
    """One agent run (root or subagent) inside a Runner run."""

    def __init__(
        self,
        *,
        run_id: str,
        spec: AgentSpec,
        backend: Backend,
        sink: Sink,
        agent_path: str = "main",
    ) -> None:
        self.run_id = run_id
        self.spec = spec
        self.backend = backend
        self.agent_path = agent_path
        self._sink = sink
        self._turn_text: list[str] = []
        self.output = ""
        """Text of this agent's final turn — the run's answer."""
        self.tools: dict[str, ToolSpec] = {t.name: t for t in spec.tools}
        self._subagents: dict[str, AgentSpec] = {}
        for sub in spec.subagents:
            name = delegate_tool_name(sub.name)
            self._subagents[name] = sub
            self.tools[name] = _delegate_tool(sub)

    async def emit(self, event: AgentEvent) -> None:
        event.agent = self.agent_path
        match event:
            case TurnStarted():
                self._turn_text = []
            case TextDelta(text=text):
                self._turn_text.append(text)
            case TurnCompleted():
                self.output = "".join(self._turn_text)
            case _:
                pass
        await self._sink(event)

    async def execute_tool(self, call_id: str, name: str, raw_input: dict[str, Any]) -> ToolOutcome:
        """Run one tool call. Never raises except BackendError (the run must fail)."""
        sub = self._subagents.get(name)
        if sub is not None:
            task = raw_input.get("task")
            await self.emit(
                SubagentStarted(
                    call_id=call_id, name=sub.name, task=task if isinstance(task, str) else ""
                )
            )
        else:
            await self.emit(ToolCall(call_id=call_id, name=name, input=raw_input))

        started = time.perf_counter()
        if sub is not None:
            content, is_error = await self._delegate(sub, call_id, raw_input)
        else:
            content, is_error = await self._invoke(self.tools.get(name), name, raw_input)
        content = clip(content, self.spec.context.tool_result_max_chars)
        duration_ms = round((time.perf_counter() - started) * 1000)

        if sub is not None:
            await self.emit(
                SubagentCompleted(
                    call_id=call_id,
                    name=sub.name,
                    output=content,
                    is_error=is_error,
                    duration_ms=duration_ms,
                )
            )
        else:
            await self.emit(
                ToolResult(
                    call_id=call_id,
                    name=name,
                    output=content,
                    is_error=is_error,
                    duration_ms=duration_ms,
                )
            )
        return ToolOutcome(content=content, is_error=is_error)

    async def _invoke(
        self, spec: ToolSpec | None, name: str, raw_input: dict[str, Any]
    ) -> tuple[str, bool]:
        # Every failure goes back to the model as an error result so it can recover or explain.
        if spec is None:
            return f"Unknown tool: {name}", True
        args = _validate(spec.input_model, raw_input)
        if isinstance(args, str):
            return args, True
        timeout = spec.timeout_s or self.spec.loop.tool_timeout_s
        try:
            result = await asyncio.wait_for(spec.handler(args), timeout)
        except TimeoutError:
            return f"Tool timed out after {timeout}s", True
        except BackendError:
            raise
        except Exception as exc:
            logger.exception("tool failed", extra={"tool": name, "agent": self.agent_path})
            return f"Tool failed: {type(exc).__name__}: {exc}"[:2000], True
        if not isinstance(result, str):
            return f"Tool returned {type(result).__name__}, expected text", True
        return result, False

    async def _delegate(
        self, sub: AgentSpec, call_id: str, raw_input: dict[str, Any]
    ) -> tuple[str, bool]:
        args = _validate(DelegateInput, raw_input)
        if isinstance(args, str):
            return args, True
        assert isinstance(args, DelegateInput)  # noqa: S101 — narrowed by _validate(DelegateInput)
        child = RunContext(
            run_id=self.run_id,
            spec=sub,
            backend=self.backend,
            sink=self._sink,
            agent_path=child_agent_path(self.agent_path, sub.name, call_id),
        )
        # A child's BackendError propagates: the whole run fails, as on every backend.
        result = await self.backend.run(child, args.task, None)
        if result.stop_reason != "end_turn":
            return (
                f"{child.output}\n\n[subagent stopped early: {result.stop_reason}]".strip(),
                False,
            )
        return child.output, False


def _json_numbers(value: Any) -> Any:
    """`5.0` -> `5`, as a JavaScript round-trip does (the Agent SDK's CLI), so whole-number
    floats validate the same on every backend."""
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, dict):
        return {k: _json_numbers(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_numbers(v) for v in value]
    return value


def _validate(model: type[BaseModel], raw_input: dict[str, Any]) -> BaseModel | str:
    raw_input = _json_numbers(raw_input)
    try:
        # Strict JSON mode, nested models included: accepts what JSON Schema accepts
        # (enum strings, ISO datetimes) and nothing it rejects (`"5"` for an int).
        return model.model_validate_json(json.dumps(raw_input), strict=True)
    except ValidationError as exc:
        return f"Invalid input: {exc.errors(include_url=False, include_context=False)}"


def _delegate_tool(sub: AgentSpec) -> ToolSpec:
    async def unreachable(args: Any) -> str:
        raise RuntimeError("delegation runs through RunContext.execute_tool")

    return ToolSpec(
        name=delegate_tool_name(sub.name),
        description=delegate_description(sub),
        input_model=DelegateInput,
        handler=unreachable,
        kind="subagent",
    )


async def gather_all[T](*aws: Coroutine[Any, Any, T]) -> list[T]:
    """`asyncio.gather` that cancels the rest when one fails — no orphaned tool or subagent work
    keeps running after the run has already failed."""
    try:
        async with asyncio.TaskGroup() as group:
            tasks = [group.create_task(aw) for aw in aws]
    except BaseExceptionGroup as failed:
        raise first_error(failed) from None
    return [task.result() for task in tasks]


def first_error(group: BaseExceptionGroup[Any]) -> BaseException:
    leaves: list[BaseException] = []

    def walk(exc: BaseException) -> None:
        if isinstance(exc, BaseExceptionGroup):
            for inner in exc.exceptions:
                walk(inner)
        else:
            leaves.append(exc)

    walk(group)
    return next((e for e in leaves if isinstance(e, BackendError)), leaves[0])


class Runner:
    def __init__(
        self,
        backends: Mapping[str, Backend],
        store: SessionStore,
        *,
        run_timeout_s: float | None = None,
    ) -> None:
        self._backends = dict(backends)
        self._store = store
        # Upper bound for one run, subagents included. Callers rely on it to reap stale runs.
        self.run_timeout_s = run_timeout_s

    @property
    def backend_names(self) -> list[str]:
        return sorted(self._backends)

    async def stream(
        self,
        *,
        spec: AgentSpec,
        prompt: str,
        backend: str,
        session_id: str,
        run_id: str | None = None,
    ) -> AsyncIterator[AgentEvent]:
        """Run one turn of a session. Closing the iterator cancels the run."""
        impl = self._backends[backend]
        run_id = run_id or uuid.uuid4().hex
        queue: asyncio.Queue[AgentEvent | None] = asyncio.Queue()
        observer = Observer(run_id=run_id, agent=spec.name, backend=backend)
        seq = 0

        async def sink(event: AgentEvent) -> None:
            nonlocal seq
            seq += 1
            event.run_id, event.seq, event.ts = run_id, seq, time.time()
            observer.on_event(event)
            await queue.put(event)

        root = RunContext(run_id=run_id, spec=spec, backend=impl, sink=sink)

        async def drive() -> None:
            started = time.perf_counter()
            try:
                await root.emit(
                    RunStarted(backend=backend, model=spec.model, session_id=session_id)
                )
                # Shielded: cancelling mid-query can leave the DB connection locked.
                state = await asyncio.shield(self._store.load_state(session_id))
                async with asyncio.timeout(self.run_timeout_s):
                    result = await impl.run(root, prompt, state)
                await asyncio.shield(self._store.save_state(session_id, result.state))
                await root.emit(
                    RunCompleted(
                        session_id=session_id,
                        stop_reason=result.stop_reason,
                        output=root.output,
                        turns=observer.turns,
                        usage=observer.usage,
                        duration_ms=round((time.perf_counter() - started) * 1000),
                    )
                )
            except BackendError as exc:
                await root.emit(RunFailed(code=exc.code, message=exc.message))
            except TimeoutError:
                await root.emit(
                    RunFailed(code="RUN_TIMEOUT", message="실행 시간이 제한을 넘었습니다.")
                )
            except Exception:
                logger.exception("agent run failed", extra={"run_id": run_id, "backend": backend})
                await root.emit(
                    RunFailed(
                        code="AGENT_RUN_FAILED", message="에이전트 실행 중 오류가 발생했습니다."
                    )
                )
            finally:
                await queue.put(None)

        task = asyncio.create_task(drive())
        try:
            while (event := await queue.get()) is not None:
                yield event
        finally:
            if not task.done():
                task.cancel()
                # Wait without awaiting the task itself: under anyio (sse-starlette) a cancelled
                # host is re-cancelled every loop, and awaiting `task` would forward each one into
                # it — cutting backend cleanup (CLI shutdown, stream close) at its first await.
                with anyio.move_on_after(CLEANUP_TIMEOUT_S, shield=True):
                    await asyncio.wait({task})
            observer.close()


class InMemorySessionStore:
    """Process memory. For tests and single-process demos only."""

    def __init__(self) -> None:
        self._states: dict[str, SessionState | None] = {}

    async def load_state(self, session_id: str) -> SessionState | None:
        return self._states.get(session_id)

    async def save_state(self, session_id: str, state: SessionState | None) -> None:
        self._states[session_id] = state
