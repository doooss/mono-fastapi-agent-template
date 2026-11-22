"""Deterministic backend for tests — no model calls.

Plays scripted turns through the same RunContext path (emit / execute_tool) the real backends
use, so runtime, observability and the HTTP layer are tested end to end without the network.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from agent_core.events import TextDelta, TurnCompleted, TurnStarted, Usage
from agent_core.runtime import BackendResult, RunContext, SessionState


@dataclass(frozen=True)
class ScriptedTurn:
    text: str = ""
    tool_calls: Sequence[tuple[str, dict[str, Any]]] = ()
    usage: Usage = field(default_factory=lambda: Usage(input_tokens=10, output_tokens=5))


class ScriptedBackend:
    """`turns[agent_name]` is replayed from the start on every run of that agent."""

    name = "scripted"

    def __init__(
        self, turns: Mapping[str, Sequence[ScriptedTurn]], *, fail_with: Exception | None = None
    ) -> None:
        self._turns = turns
        self._fail_with = fail_with

    async def run(self, ctx: RunContext, prompt: str, state: SessionState | None) -> BackendResult:
        if self._fail_with:
            raise self._fail_with
        prompts = [*(state or {}).get("prompts", []), prompt]
        for number, turn in enumerate(self._turns.get(ctx.spec.name, ()), start=1):
            if number > ctx.spec.loop.max_turns:
                return BackendResult("max_turns", {"prompts": prompts})
            await ctx.emit(TurnStarted(turn=number, model=ctx.spec.model))
            if turn.text:
                await ctx.emit(TextDelta(text=turn.text))
            await ctx.emit(
                TurnCompleted(
                    turn=number,
                    stop_reason="tool_use" if turn.tool_calls else "end_turn",
                    usage=turn.usage,
                )
            )
            for index, (name, args) in enumerate(turn.tool_calls):
                await ctx.execute_tool(f"call_{ctx.spec.name}_{number}_{index}", name, args)
        return BackendResult("end_turn", {"prompts": prompts})
