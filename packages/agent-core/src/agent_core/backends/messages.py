"""Messages API backend — the agent loop runs here.

Session state = the full message history (JSON). Server-side context management (compaction,
tool-result clearing) is applied from `ContextPolicy`; it is the only backend where those knobs
take effect.
"""

import copy
from typing import Any

import anthropic
from anthropic import AsyncAnthropic
from anthropic.types.beta import BetaMessage, BetaToolUseBlock, BetaUsage

from agent_core.backends._upstream import from_anthropic
from agent_core.context import system_prompt
from agent_core.events import (
    AgentEvent,
    ContextCompacted,
    ContextEdited,
    TextDelta,
    TurnCompleted,
    TurnStarted,
    Usage,
)
from agent_core.runtime import BackendResult, RunContext, SessionState, ToolOutcome, gather_all
from agent_core.spec import ContextPolicy

COMPACT_BETA = "compact-2026-01-12"
CONTEXT_EDIT_BETA = "context-management-2025-06-27"
_EPHEMERAL = {"type": "ephemeral"}

Message = dict[str, Any]


def usage_of(usage: BetaUsage) -> Usage:
    return Usage(
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cache_read_tokens=usage.cache_read_input_tokens or 0,
        cache_write_tokens=usage.cache_creation_input_tokens or 0,
    )


def context_management(policy: ContextPolicy) -> tuple[list[str], dict[str, Any] | None]:
    """(beta headers, `context_management` param) for the policy."""
    betas: list[str] = []
    edits: list[dict[str, Any]] = []
    if policy.clear_tool_uses_at_tokens is not None:
        betas.append(CONTEXT_EDIT_BETA)
        edits.append(
            {
                "type": "clear_tool_uses_20250919",
                "trigger": {"type": "input_tokens", "value": policy.clear_tool_uses_at_tokens},
                "keep": {"type": "tool_uses", "value": policy.keep_tool_uses},
            }
        )
    if policy.compact_at_tokens is not None:
        betas.append(COMPACT_BETA)
        edits.append(
            {
                "type": "compact_20260112",
                "trigger": {"type": "input_tokens", "value": policy.compact_at_tokens},
            }
        )
    return betas, ({"edits": edits} if edits else None)


def context_events(message: BetaMessage) -> list[AgentEvent]:
    events: list[AgentEvent] = []
    if any(block.type == "compaction" for block in message.content):
        events.append(ContextCompacted())
    if message.context_management:
        for edit in message.context_management.applied_edits:
            if edit.type == "clear_tool_uses_20250919":
                events.append(
                    ContextEdited(
                        cleared_tool_uses=edit.cleared_tool_uses,
                        cleared_input_tokens=edit.cleared_input_tokens,
                    )
                )
    return events


def append_user(history: list[Message], content: list[dict[str, Any]]) -> None:
    # A run that stopped on max_turns leaves tool results as the last user message.
    if history and history[-1]["role"] == "user":
        history[-1]["content"] = [*history[-1]["content"], *content]
    else:
        history.append({"role": "user", "content": content})


def with_cache_breakpoint(history: list[Message]) -> list[Message]:
    """Copy with a cache breakpoint on the last block, so each turn reuses the previous prefix."""
    if not history:
        return history
    *head, last = history
    blocks = [dict(block) for block in last["content"]]
    blocks[-1]["cache_control"] = _EPHEMERAL
    return [*head, {**last, "content": blocks}]


class MessagesBackend:
    name = "messages"

    def __init__(self, client: AsyncAnthropic) -> None:
        self._client = client

    async def run(self, ctx: RunContext, prompt: str, state: SessionState | None) -> BackendResult:
        spec = ctx.spec
        # Deep copy: merging into the last stored message must not touch the saved state.
        history: list[Message] = copy.deepcopy((state or {}).get("messages", []))
        append_user(history, [{"type": "text", "text": prompt}])
        betas, context_param = context_management(spec.context)
        tools = [
            {"name": t.name, "description": t.description, "input_schema": t.input_schema()}
            for t in ctx.tools.values()
        ]
        params: dict[str, Any] = {
            "model": spec.model,
            "max_tokens": spec.loop.max_tokens,
            # One breakpoint on the system prompt caches tools + system together.
            "system": [{"type": "text", "text": system_prompt(spec), "cache_control": _EPHEMERAL}],
        }
        if tools:
            params["tools"] = tools
        if betas:
            params["betas"] = betas
        if context_param:
            params["context_management"] = context_param

        def done(stop: Any) -> BackendResult:
            return BackendResult(stop, {"messages": history})

        for turn in range(1, spec.loop.max_turns + 1):
            await ctx.emit(TurnStarted(turn=turn, model=spec.model))
            try:
                async with self._client.beta.messages.stream(
                    messages=with_cache_breakpoint(history),  # type: ignore[arg-type]
                    **params,
                ) as stream:
                    async for text in stream.text_stream:
                        await ctx.emit(TextDelta(text=text))
                    message = await stream.get_final_message()
            except anthropic.AnthropicError as exc:
                raise from_anthropic(exc) from exc

            for event in context_events(message):
                await ctx.emit(event)
            await ctx.emit(
                TurnCompleted(
                    turn=turn, stop_reason=message.stop_reason, usage=usage_of(message.usage)
                )
            )
            history.append(
                {
                    "role": "assistant",
                    "content": [
                        b.model_dump(mode="json", exclude_none=True) for b in message.content
                    ],
                }
            )

            calls = [b for b in message.content if isinstance(b, BetaToolUseBlock)]
            if message.stop_reason == "refusal":
                return done("refusal")
            if message.stop_reason in ("pause_turn", "compaction"):
                continue
            if not calls:
                return done("end_turn")
            outcomes = await gather_all(*(self._call(ctx, c) for c in calls))
            append_user(
                history,
                [
                    {
                        "type": "tool_result",
                        "tool_use_id": call.id,
                        "content": outcome.content,
                        "is_error": outcome.is_error,
                    }
                    for call, outcome in zip(calls, outcomes, strict=True)
                ],
            )
        return done("max_turns")

    @staticmethod
    async def _call(ctx: RunContext, call: BetaToolUseBlock) -> ToolOutcome:
        raw = call.input if isinstance(call.input, dict) else {}
        return await ctx.execute_tool(call.id, call.name, raw)
