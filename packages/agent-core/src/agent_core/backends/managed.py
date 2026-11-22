"""Claude Managed Agents backend — the loop runs on Anthropic's servers.

Agents are created from `AgentSpec` with only custom tools (no `agent_toolset_*`, so no built-in
tools). A custom tool call arrives as `agent.custom_tool_use`; it runs through
`RunContext.execute_tool` and the result goes back as `user.custom_tool_result`.

Session state = the managed session id. Managed Agents has no max-turns knob, so the loop limit
is enforced here by interrupting the session.
"""

import asyncio
import hashlib
import json
import logging
from typing import Any

import anthropic
from anthropic import AsyncAnthropic

from agent_core.backends._upstream import from_anthropic
from agent_core.context import system_prompt
from agent_core.events import (
    AgentEvent,
    ContextCompacted,
    StopReason,
    TextDelta,
    TurnCompleted,
    TurnStarted,
    Usage,
)
from agent_core.runtime import BackendError, BackendResult, RunContext, SessionState

logger = logging.getLogger("agent_core.backends.managed")

HASH_KEY = "template_hash"
_IDLE_STOP: dict[str, StopReason] = {
    "end_turn": "end_turn",
    "refusal": "refusal",
    "budget_reached": "budget",
}


async def _settle(tasks: list[asyncio.Task[None]]) -> None:
    """Wait for tool answers; the first failure cancels the rest and is raised."""
    if not tasks:
        return
    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
    failed = next((t for t in done if not t.cancelled() and t.exception()), None)
    if failed is not None:
        for task in pending:
            task.cancel()
        raise failed.exception()  # type: ignore[misc]
    tasks.clear()


def agent_definition(ctx: RunContext) -> dict[str, Any]:
    spec = ctx.spec
    return {
        "name": spec.name,
        "description": spec.description,
        "model": spec.model,
        "system": system_prompt(spec),
        "tools": [
            {
                "type": "custom",
                "name": t.name,
                "description": t.description,
                "input_schema": t.input_schema(),
            }
            for t in ctx.tools.values()
        ],
    }


def definition_hash(definition: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(definition, sort_keys=True).encode()).hexdigest()[:16]


class ManagedTranslator:
    """Session events -> turn / text / context events.

    `agent.message` carries a whole model request's text and may arrive after
    `span.model_request_end`, so turn.completed is held until the next boundary.
    """

    def __init__(self, model: str) -> None:
        self.model = model
        self.turn = 0
        self.started = False
        self._pending_end: TurnCompleted | None = None

    def flush(self, stop_reason: str | None) -> list[AgentEvent]:
        if self._pending_end is None:
            return []
        end, self._pending_end = self._pending_end, None
        end.stop_reason = stop_reason
        return [end]

    def on_event(self, event: Any) -> list[AgentEvent]:
        match event.type:
            case "session.status_running":
                self.started = True
            case "span.model_request_start":
                self.started = True
                out = self.flush(None)
                self.turn += 1
                return [*out, TurnStarted(turn=self.turn, model=self.model)]
            case "agent.message":
                text = "".join(b.text for b in event.content if b.type == "text")
                return [TextDelta(text=text)] if text else []
            case "span.model_request_end":
                u = event.model_usage
                self._pending_end = TurnCompleted(
                    turn=self.turn,
                    stop_reason=None,
                    usage=Usage(
                        input_tokens=u.input_tokens,
                        output_tokens=u.output_tokens,
                        cache_read_tokens=u.cache_read_input_tokens,
                        cache_write_tokens=u.cache_creation_input_tokens,
                    ),
                )
            case "agent.custom_tool_use":
                return self.flush("tool_use")
            case "agent.thread_context_compacted":
                return [ContextCompacted()]
            case "session.status_idle" if self.started:
                return self.flush(event.stop_reason.type)
            case _:
                pass
        return []


class ManagedBackend:
    name = "managed"

    def __init__(self, client: AsyncAnthropic, *, environment_name: str) -> None:
        self._client = client
        self._environment_name = environment_name
        self._environment_id: str | None = None
        self._agent_ids: dict[str, str] = {}
        self._provision_lock = asyncio.Lock()
        self._background: set[asyncio.Task[None]] = set()

    async def run(self, ctx: RunContext, prompt: str, state: SessionState | None) -> BackendResult:
        try:
            return await self._run(ctx, prompt, state)
        except anthropic.AnthropicError as exc:
            raise from_anthropic(exc) from exc

    async def _run(self, ctx: RunContext, prompt: str, state: SessionState | None) -> BackendResult:
        sessions = self._client.beta.sessions
        session_id = (state or {}).get("managed_session_id")
        if not session_id:
            environment_id, agent_id = await self._provision(ctx)
            session = await sessions.create(agent=agent_id, environment_id=environment_id)
            session_id = session.id
        keep = {"managed_session_id": session_id}

        translator = ManagedTranslator(ctx.spec.model)
        answering: list[asyncio.Task[None]] = []
        stream = await sessions.events.stream(session_id)
        try:
            async with stream:
                # Stream first, then send: nothing between the two is missed.
                await sessions.events.send(
                    session_id,
                    events=[
                        {"type": "user.message", "content": [{"type": "text", "text": prompt}]}
                    ],
                )
                async for event in stream:
                    if (
                        event.type == "span.model_request_start"
                        and translator.turn >= ctx.spec.loop.max_turns
                    ):
                        await self._interrupt(session_id)
                        return BackendResult("max_turns", keep)

                    for out in translator.on_event(event):
                        await ctx.emit(out)

                    match event.type:
                        case "agent.custom_tool_use":
                            answering.append(
                                asyncio.create_task(self._answer(ctx, session_id, event))
                            )
                        case "session.status_idle" if translator.started:
                            reason = event.stop_reason.type
                            if reason == "requires_action":
                                await _settle(answering)
                                continue
                            if reason == "retries_exhausted":
                                raise BackendError(
                                    "UPSTREAM_UNAVAILABLE", "모델 서비스가 응답하지 않습니다."
                                )
                            await _settle(answering)
                            return BackendResult(_IDLE_STOP.get(reason, "end_turn"), keep)
                        case "session.status_terminated":
                            raise BackendError(
                                "UPSTREAM_SESSION_TERMINATED", "에이전트 세션이 종료되었습니다."
                            )
                        case "session.error" if event.error.retry_status.type != "retrying":
                            logger.warning(
                                "managed session error",
                                extra={"error": event.error.type, "session": session_id},
                            )
                            raise BackendError(
                                "UPSTREAM_ERROR", "에이전트 세션에서 오류가 발생했습니다."
                            )
                        case _:
                            pass
        except BaseException:
            # Failed or client went away: stop the server-side loop too. Fire and forget —
            # we may be cancelled, and the run's outcome no longer depends on it.
            task = asyncio.ensure_future(self._interrupt(session_id))
            self._background.add(task)
            task.add_done_callback(self._background.discard)
            raise
        finally:
            # No tool / subagent work outlives the run.
            for pending in answering:
                pending.cancel()
        raise BackendError("UPSTREAM_ERROR", "에이전트 세션 스트림이 예기치 않게 끝났습니다.")

    async def _answer(self, ctx: RunContext, session_id: str, event: Any) -> None:
        outcome = await ctx.execute_tool(event.id, event.name, dict(event.input))
        result: dict[str, Any] = {
            "type": "user.custom_tool_result",
            "custom_tool_use_id": event.id,
            "is_error": outcome.is_error,
        }
        if outcome.content:
            result["content"] = [{"type": "text", "text": outcome.content}]
        await self._client.beta.sessions.events.send(session_id, events=[result])  # type: ignore[list-item]

    async def _interrupt(self, session_id: str) -> None:
        try:
            await self._client.beta.sessions.events.send(
                session_id, events=[{"type": "user.interrupt"}]
            )
        except anthropic.AnthropicError:
            logger.warning("interrupt failed", extra={"session": session_id})

    async def _provision(self, ctx: RunContext) -> tuple[str, str]:
        """Find or create the environment and an agent matching the current spec.

        A spec change yields a new hash and therefore a new agent; old ones stay until archived.
        """
        definition = agent_definition(ctx)
        digest = definition_hash(definition)
        async with self._provision_lock:
            if self._environment_id is None:
                self._environment_id = await self._find_or_create_environment()
            if digest not in self._agent_ids:
                self._agent_ids[digest] = await self._find_or_create_agent(definition, digest)
            return self._environment_id, self._agent_ids[digest]

    async def _find_or_create_environment(self) -> str:
        async for env in self._client.beta.environments.list():
            if env.name == self._environment_name:
                return env.id
        env = await self._client.beta.environments.create(
            name=self._environment_name,
            config={"type": "cloud", "networking": {"type": "limited"}},
        )
        return env.id

    async def _find_or_create_agent(self, definition: dict[str, Any], digest: str) -> str:
        async for agent in self._client.beta.agents.list():
            if agent.name == definition["name"] and (agent.metadata or {}).get(HASH_KEY) == digest:
                return agent.id
        agent = await self._client.beta.agents.create(**definition, metadata={HASH_KEY: digest})
        return agent.id
