"""Backend-neutral event contract.

Every backend emits only these events. SSE, logs, traces, run totals and the final output are
derived from this stream alone, so the three backends are rendered and observed the same way.
"""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, computed_field

StopReason = Literal["end_turn", "max_turns", "refusal", "budget", "cancelled"]


class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def context_tokens(self) -> int:
        # Prompt size the model saw. Uncached input alone undercounts once caching kicks in.
        return self.input_tokens + self.cache_read_tokens + self.cache_write_tokens

    def __add__(self, other: Usage) -> Usage:
        return Usage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cache_read_tokens=self.cache_read_tokens + other.cache_read_tokens,
            cache_write_tokens=self.cache_write_tokens + other.cache_write_tokens,
        )


def child_agent_path(parent: str, name: str, call_id: str) -> str:
    """`agent` of a delegated run. The call id keeps parallel runs of one subagent apart."""
    return f"{parent}/{name}#{call_id}"


class _Event(BaseModel):
    # Envelope: `agent` is set by RunContext, the rest by the Runner. Backends leave defaults.
    run_id: str = ""
    seq: int = 0
    ts: float = 0.0
    agent: str = "main"


class RunStarted(_Event):
    type: Literal["run.started"] = "run.started"
    backend: str
    model: str
    session_id: str


class TurnStarted(_Event):
    """One model request. Numbered per agent."""

    type: Literal["turn.started"] = "turn.started"
    turn: int
    model: str


class TextDelta(_Event):
    type: Literal["text.delta"] = "text.delta"
    text: str


class TurnCompleted(_Event):
    type: Literal["turn.completed"] = "turn.completed"
    turn: int
    stop_reason: str | None
    usage: Usage


class ToolCall(_Event):
    type: Literal["tool.call"] = "tool.call"
    call_id: str
    name: str
    input: dict[str, Any]


class ToolResult(_Event):
    type: Literal["tool.result"] = "tool.result"
    call_id: str
    name: str
    output: str
    is_error: bool
    duration_ms: int


class SubagentStarted(_Event):
    type: Literal["subagent.started"] = "subagent.started"
    call_id: str
    name: str
    task: str


class SubagentCompleted(_Event):
    type: Literal["subagent.completed"] = "subagent.completed"
    call_id: str
    name: str
    output: str
    is_error: bool
    duration_ms: int


class ContextCompacted(_Event):
    type: Literal["context.compacted"] = "context.compacted"
    pre_tokens: int | None = None


class ContextEdited(_Event):
    type: Literal["context.edited"] = "context.edited"
    cleared_tool_uses: int = 0
    cleared_input_tokens: int = 0


class RunCompleted(_Event):
    type: Literal["run.completed"] = "run.completed"
    session_id: str
    stop_reason: StopReason
    output: str
    turns: int
    usage: Usage
    duration_ms: int


class RunFailed(_Event):
    type: Literal["run.failed"] = "run.failed"
    code: str
    message: str


AgentEvent = Annotated[
    RunStarted
    | TurnStarted
    | TextDelta
    | TurnCompleted
    | ToolCall
    | ToolResult
    | SubagentStarted
    | SubagentCompleted
    | ContextCompacted
    | ContextEdited
    | RunCompleted
    | RunFailed,
    Field(discriminator="type"),
]

TERMINAL_EVENTS = frozenset({"run.completed", "run.failed"})
