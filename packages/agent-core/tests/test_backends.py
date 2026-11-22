"""Native stream -> AgentEvent translation. Inputs use the real SDK types / raw event shapes."""

import asyncio
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from anthropic.types.beta import BetaMessage
from claude_agent_sdk import ResultMessage

from agent_core import (
    AgentSpec,
    BackendError,
    ContextCompacted,
    ContextEdited,
    InMemorySessionStore,
    RunFailed,
    Runner,
    TextDelta,
    TurnCompleted,
    TurnStarted,
)
from agent_core.backends.agent_sdk import (
    AgentSdkBackend,
    CallIds,
    StreamTranslator,
    result_stop_reason,
)
from agent_core.backends.managed import ManagedTranslator
from agent_core.backends.messages import append_user, context_events


def test_sdk_stream_events_become_one_turn_with_merged_usage() -> None:
    t = StreamTranslator("m")
    raw: list[dict[str, Any]] = [
        {
            "type": "message_start",
            "message": {"usage": {"input_tokens": 12, "cache_read_input_tokens": 100}},
        },
        {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Hel"}},
        {"type": "content_block_delta", "delta": {"type": "input_json_delta", "partial_json": "{"}},
        {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "lo"}},
        {
            "type": "message_delta",
            "delta": {"stop_reason": "tool_use"},
            "usage": {"output_tokens": 9},
        },
        {"type": "message_stop"},
    ]
    events = [e for r in raw for e in t.on_event(r)]

    assert [type(e) for e in events] == [TurnStarted, TextDelta, TextDelta, TurnCompleted]
    end = events[-1]
    assert isinstance(end, TurnCompleted)
    assert (end.stop_reason, end.usage.input_tokens, end.usage.cache_read_tokens) == (
        "tool_use",
        12,
        100,
    )
    assert end.usage.output_tokens == 9
    assert not t.turn_open


def test_managed_turn_end_waits_for_late_text_and_takes_the_tool_use_reason() -> None:
    t = ManagedTranslator("m")
    usage = SimpleNamespace(
        input_tokens=5, output_tokens=2, cache_read_input_tokens=1, cache_creation_input_tokens=0
    )
    stream = [
        SimpleNamespace(type="session.status_idle", stop_reason=SimpleNamespace(type="end_turn")),
        SimpleNamespace(type="session.status_running"),
        SimpleNamespace(type="span.model_request_start"),
        SimpleNamespace(type="span.model_request_end", model_usage=usage),
        SimpleNamespace(type="agent.message", content=[SimpleNamespace(type="text", text="late")]),
        SimpleNamespace(type="agent.custom_tool_use"),
        SimpleNamespace(type="agent.thread_context_compacted"),
    ]
    events = [e for ev in stream for e in t.on_event(ev)]

    # The idle replayed before this run started is ignored.
    assert [type(e) for e in events] == [TurnStarted, TextDelta, TurnCompleted, ContextCompacted]
    end = events[2]
    assert isinstance(end, TurnCompleted)
    assert (end.stop_reason, end.usage.context_tokens) == ("tool_use", 6)


def test_messages_context_events_from_compaction_and_applied_edits() -> None:
    message = BetaMessage.model_validate(
        {
            "id": "m",
            "type": "message",
            "role": "assistant",
            "model": "m",
            "content": [
                {"type": "compaction", "content": "summary"},
                {"type": "text", "text": "hi"},
            ],
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": {"input_tokens": 1, "output_tokens": 1},
            "context_management": {
                "applied_edits": [
                    {
                        "type": "clear_tool_uses_20250919",
                        "cleared_tool_uses": 4,
                        "cleared_input_tokens": 900,
                    }
                ]
            },
        }
    )
    events = context_events(message)

    assert isinstance(events[0], ContextCompacted)
    assert isinstance(events[1], ContextEdited)
    assert (events[1].cleared_tool_uses, events[1].cleared_input_tokens) == (4, 900)


def test_new_prompt_merges_into_trailing_tool_results() -> None:
    history: list[dict[str, Any]] = [
        {
            "role": "assistant",
            "content": [{"type": "tool_use", "id": "t", "name": "x", "input": {}}],
        },
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t", "content": "r"}]},
    ]
    append_user(history, [{"type": "text", "text": "next"}])

    assert len(history) == 2
    assert [b["type"] for b in history[-1]["content"]] == ["tool_result", "text"]


async def test_call_ids_match_handler_args_to_stream_ids_in_either_order() -> None:
    ids = CallIds()
    waiting = asyncio.create_task(ids.claim("search", {"b": 1, "a": "x"}))
    await asyncio.sleep(0)
    await ids.offer("search", {"a": "x", "b": 1}, "toolu_1")
    await ids.offer("search", {"a": "y"}, "toolu_2")

    assert await waiting == "toolu_1"
    assert await ids.claim("search", {"a": "y"}) == "toolu_2"


def _result(**overrides: Any) -> ResultMessage:
    base: dict[str, Any] = {
        "subtype": "success",
        "duration_ms": 1,
        "duration_api_ms": 1,
        "is_error": False,
        "num_turns": 1,
        "session_id": "s",
    }
    return ResultMessage(**(base | overrides))


def test_sdk_api_failures_reported_as_success_fail_the_run() -> None:
    assert result_stop_reason(_result()) == "end_turn"
    assert result_stop_reason(_result(subtype="error_max_turns", is_error=True)) == "max_turns"
    for status, code in [
        (429, "UPSTREAM_RATE_LIMITED"),
        (529, "UPSTREAM_UNAVAILABLE"),
        (401, "UPSTREAM_ERROR"),
    ]:
        with pytest.raises(BackendError) as failed:
            result_stop_reason(_result(is_error=True, api_error_status=status))
        assert failed.value.code == code


async def test_sdk_session_without_a_local_transcript_fails_before_starting_the_cli(
    tmp_path: Path,
) -> None:
    backend = AgentSdkBackend(api_key=None, workdir=tmp_path)
    store = InMemorySessionStore()
    await store.save_state("s", {"sdk_session_id": str(uuid.uuid4())})
    runner = Runner({"agent_sdk": backend}, store)
    agent = AgentSpec(name="a", description="d", model="m", instructions=("x",))

    events = [
        e async for e in runner.stream(spec=agent, prompt="p", backend="agent_sdk", session_id="s")
    ]

    assert isinstance(events[-1], RunFailed)
    assert events[-1].code == "SESSION_STATE_LOST"
