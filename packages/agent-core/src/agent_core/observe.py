"""Observability derived from the event stream only.

Logs, OpenTelemetry spans and run totals are computed here from `AgentEvent`s — never from a
backend's native hooks — so every backend is observed identically. Spans follow the OTel GenAI
semantic conventions and use event timestamps, so they are a faithful replay of the stream.
Without an OTel SDK configured the API is a no-op.
"""

import logging
from typing import Any

from opentelemetry import trace
from opentelemetry.trace import Span, Status, StatusCode

from agent_core.events import (
    AgentEvent,
    ContextCompacted,
    ContextEdited,
    RunCompleted,
    RunFailed,
    RunStarted,
    SubagentCompleted,
    SubagentStarted,
    TextDelta,
    ToolCall,
    ToolResult,
    TurnCompleted,
    TurnStarted,
    Usage,
    child_agent_path,
)

logger = logging.getLogger("agent_core.events")
_tracer = trace.get_tracer("agent_core")


def _ns(ts: float) -> int:
    return int(ts * 1_000_000_000)


def log_fields(event: AgentEvent) -> dict[str, Any]:
    """Structured log fields. Never includes prompt, output, tool input or tool output text."""
    base: dict[str, Any] = {"event": event.type, "run_id": event.run_id, "agent": event.agent}
    match event:
        case RunStarted():
            base |= {"backend": event.backend, "model": event.model, "session_id": event.session_id}
        case TurnStarted():
            base |= {"turn": event.turn, "model": event.model}
        case TurnCompleted():
            base |= {
                "turn": event.turn,
                "stop_reason": event.stop_reason,
                **event.usage.model_dump(),
            }
        case ToolCall():
            base |= {"call_id": event.call_id, "tool": event.name}
        case ToolResult():
            base |= {
                "call_id": event.call_id,
                "tool": event.name,
                "is_error": event.is_error,
                "duration_ms": event.duration_ms,
            }
        case SubagentStarted():
            base |= {"call_id": event.call_id, "subagent": event.name}
        case SubagentCompleted():
            base |= {
                "call_id": event.call_id,
                "subagent": event.name,
                "is_error": event.is_error,
                "duration_ms": event.duration_ms,
            }
        case ContextCompacted():
            base |= {"pre_tokens": event.pre_tokens}
        case ContextEdited():
            base |= {
                "cleared_tool_uses": event.cleared_tool_uses,
                "cleared_input_tokens": event.cleared_input_tokens,
            }
        case RunCompleted():
            base |= {
                "stop_reason": event.stop_reason,
                "turns": event.turns,
                "duration_ms": event.duration_ms,
                **event.usage.model_dump(),
            }
        case RunFailed():
            base |= {"code": event.code}
        case _:
            pass
    return base


class Observer:
    def __init__(self, *, run_id: str, agent: str, backend: str) -> None:
        self.run_id = run_id
        self.agent = agent
        self.backend = backend
        self.usage = Usage()
        self.turns = 0
        self.tool_calls = 0
        self.tool_errors = 0
        self._agent_spans: dict[str, Span] = {}
        self._turn_spans: dict[str, Span] = {}
        self._tool_spans: dict[str, Span] = {}

    def on_event(self, event: AgentEvent) -> None:
        if not isinstance(event, TextDelta):
            level = logging.WARNING if getattr(event, "is_error", False) else logging.INFO
            if isinstance(event, RunFailed):
                level = logging.ERROR
            logger.log(level, event.type, extra=log_fields(event))
        self._aggregate(event)
        self._trace(event)

    def _aggregate(self, event: AgentEvent) -> None:
        match event:
            case TurnCompleted():
                self.turns += 1
                self.usage = self.usage + event.usage
            case ToolResult() | SubagentCompleted():
                self.tool_calls += 1
                self.tool_errors += int(event.is_error)
            case _:
                pass

    def _start(self, name: str, parent: Span | None, ts: float, attrs: dict[str, Any]) -> Span:
        ctx = trace.set_span_in_context(parent) if parent else None
        return _tracer.start_span(name, context=ctx, start_time=_ns(ts), attributes=attrs)

    def _trace(self, event: AgentEvent) -> None:
        parent = self._agent_spans.get(event.agent)
        match event:
            case RunStarted():
                self._agent_spans[event.agent] = self._start(
                    f"invoke_agent {self.agent}",
                    None,
                    event.ts,
                    {
                        "gen_ai.operation.name": "invoke_agent",
                        "gen_ai.provider.name": "anthropic",
                        "gen_ai.agent.name": self.agent,
                        "gen_ai.request.model": event.model,
                        "gen_ai.conversation.id": event.session_id,
                        "agent.backend": event.backend,
                        "agent.run_id": self.run_id,
                    },
                )
            case SubagentStarted():
                self._agent_spans[child_agent_path(event.agent, event.name, event.call_id)] = (
                    self._start(
                        f"invoke_agent {event.name}",
                        parent,
                        event.ts,
                        {
                            "gen_ai.operation.name": "invoke_agent",
                            "gen_ai.agent.name": event.name,
                            "gen_ai.tool.call.id": event.call_id,
                        },
                    )
                )
            case SubagentCompleted():
                span = self._agent_spans.pop(
                    child_agent_path(event.agent, event.name, event.call_id), None
                )
                if span:
                    if event.is_error:
                        span.set_status(Status(StatusCode.ERROR))
                    span.end(end_time=_ns(event.ts))
            case TurnStarted():
                self._turn_spans[event.agent] = self._start(
                    f"chat {event.model}",
                    parent,
                    event.ts,
                    {"gen_ai.operation.name": "chat", "gen_ai.request.model": event.model},
                )
            case TurnCompleted():
                span = self._turn_spans.pop(event.agent, None)
                if span:
                    usage = event.usage
                    span.set_attributes(
                        {
                            "gen_ai.usage.input_tokens": usage.input_tokens,
                            "gen_ai.usage.output_tokens": usage.output_tokens,
                            "gen_ai.usage.cache_read.input_tokens": usage.cache_read_tokens,
                            "gen_ai.usage.cache_creation.input_tokens": usage.cache_write_tokens,
                            "gen_ai.response.finish_reasons": [event.stop_reason or ""],
                        }
                    )
                    span.end(end_time=_ns(event.ts))
            case ToolCall():
                self._tool_spans[event.call_id] = self._start(
                    f"execute_tool {event.name}",
                    parent,
                    event.ts,
                    {
                        "gen_ai.operation.name": "execute_tool",
                        "gen_ai.tool.name": event.name,
                        "gen_ai.tool.call.id": event.call_id,
                    },
                )
            case ToolResult():
                span = self._tool_spans.pop(event.call_id, None)
                if span:
                    if event.is_error:
                        span.set_status(Status(StatusCode.ERROR))
                    span.end(end_time=_ns(event.ts))
            case ContextCompacted() | ContextEdited():
                if parent:
                    parent.add_event(
                        event.type, attributes=log_fields(event), timestamp=_ns(event.ts)
                    )
            case RunCompleted() | RunFailed():
                root = self._agent_spans.pop("main", None)
                if root:
                    if isinstance(event, RunFailed):
                        root.set_status(Status(StatusCode.ERROR, event.code))
                    else:
                        root.set_attribute("agent.stop_reason", event.stop_reason)
                    root.end(end_time=_ns(event.ts))
            case _:
                pass

    def close(self) -> None:
        """End anything still open (cancelled or failed runs) so no span leaks."""
        for spans in (self._tool_spans, self._turn_spans, self._agent_spans):
            for span in spans.values():
                span.end()
            spans.clear()
