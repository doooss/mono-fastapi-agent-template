import asyncio

import anyio
import pytest

from agent_core import (
    AgentEvent,
    AgentSpec,
    BackendError,
    BackendResult,
    ContextPolicy,
    InMemorySessionStore,
    LoopPolicy,
    RunCompleted,
    RunContext,
    RunFailed,
    Runner,
    SessionState,
    SubagentCompleted,
    ToolInput,
    ToolResult,
    Usage,
    tool,
)
from agent_core.runtime import gather_all
from agent_core.testing import ScriptedBackend, ScriptedTurn


class EchoInput(ToolInput):
    text: str


@tool()
async def echo(args: EchoInput) -> str:
    """Echo text back."""
    return args.text


@tool(timeout_s=0.01)
async def slow(args: EchoInput) -> str:
    """Never finishes in time."""
    await asyncio.sleep(1)
    return args.text


@tool()
async def broken(args: EchoInput) -> str:
    """Always raises."""
    raise RuntimeError("db down")


def spec(**overrides: object) -> AgentSpec:
    base: dict[str, object] = {
        "name": "main_agent",
        "description": "test",
        "model": "m",
        "instructions": ("x",),
        "tools": (echo, slow, broken),
        "context": ContextPolicy(tool_result_max_chars=5, compact_at_tokens=None),
    }
    return AgentSpec(**(base | overrides))  # type: ignore[arg-type]


async def collect(runner: Runner, agent: AgentSpec, session_id: str = "s1") -> list[AgentEvent]:
    return [
        e
        async for e in runner.stream(
            spec=agent, prompt="hi", backend="scripted", session_id=session_id
        )
    ]


async def test_tool_failures_return_error_results_and_the_run_continues() -> None:
    backend = ScriptedBackend(
        {
            "main_agent": [
                ScriptedTurn(
                    tool_calls=[
                        ("echo", {"text": "abcdefghij"}),
                        ("echo", {"wrong": 1}),
                        ("missing", {}),
                        ("slow", {"text": "x"}),
                        ("broken", {"text": "x"}),
                    ]
                ),
                ScriptedTurn(text="done"),
            ]
        }
    )
    events = await collect(Runner({"scripted": backend}, InMemorySessionStore()), spec())

    results = [e for e in events if isinstance(e, ToolResult)]
    assert [(r.name, r.is_error) for r in results] == [
        ("echo", False),
        ("echo", True),
        ("missing", True),
        ("slow", True),
        ("broken", True),
    ]
    assert results[0].output.startswith("abcde\n\n[truncated: 5")
    assert isinstance(events[-1], RunCompleted)
    assert events[-1].output == "done"
    assert [e.seq for e in events] == list(range(1, len(events) + 1))


async def test_subagent_events_nest_and_totals_cover_every_agent() -> None:
    researcher = AgentSpec(name="researcher", description="r", model="m2", instructions=("r",))
    parent = spec(tools=(), subagents=(researcher,), context=ContextPolicy(compact_at_tokens=None))
    backend = ScriptedBackend(
        {
            "main_agent": [
                ScriptedTurn(
                    text="checking", tool_calls=[("delegate_to_researcher", {"task": "q"})]
                ),
                ScriptedTurn(text="final answer"),
            ],
            "researcher": [
                ScriptedTurn(text="finding", usage=Usage(input_tokens=7, output_tokens=3))
            ],
        }
    )
    events = await collect(Runner({"scripted": backend}, InMemorySessionStore()), parent)

    kinds = [(e.type, e.agent) for e in events]
    assert ("subagent.started", "main") in kinds
    assert ("turn.started", "main/researcher#call_main_agent_1_0") in kinds
    completed = next(e for e in events if e.type == "subagent.completed")
    assert isinstance(completed, SubagentCompleted)
    assert completed.output == "finding"
    final = events[-1]
    assert isinstance(final, RunCompleted)
    assert final.output == "final answer"
    assert final.turns == 3
    assert final.usage.input_tokens == 10 + 7 + 10


async def test_max_turns_and_session_state_carry_over() -> None:
    store = InMemorySessionStore()
    backend = ScriptedBackend({"main_agent": [ScriptedTurn(text="a"), ScriptedTurn(text="b")]})
    runner = Runner({"scripted": backend}, store)
    limited = spec(loop=LoopPolicy(max_turns=1))

    first = await collect(runner, limited)
    await collect(runner, limited)

    assert isinstance(first[-1], RunCompleted)
    assert first[-1].stop_reason == "max_turns"
    assert await store.load_state("s1") == {"prompts": ["hi", "hi"]}


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (BackendError("UPSTREAM_UNAVAILABLE", "down"), "UPSTREAM_UNAVAILABLE"),
        (RuntimeError("x"), "AGENT_RUN_FAILED"),
    ],
)
async def test_backend_failure_ends_with_run_failed(error: Exception, code: str) -> None:
    store = InMemorySessionStore()
    events = await collect(
        Runner({"scripted": ScriptedBackend({}, fail_with=error)}, store), spec()
    )

    assert isinstance(events[-1], RunFailed)
    assert events[-1].code == code
    assert await store.load_state("s1") is None


async def test_run_timeout_fails_the_run_and_keeps_the_previous_state() -> None:
    class Hanging(ScriptedBackend):
        async def run(
            self, ctx: RunContext, prompt: str, state: SessionState | None
        ) -> BackendResult:
            await asyncio.sleep(10)
            raise AssertionError("unreachable")

    store = InMemorySessionStore()
    await store.save_state("s1", {"prompts": ["earlier"]})
    runner = Runner({"scripted": Hanging({})}, store, run_timeout_s=0.01)
    events = await collect(runner, spec())

    assert isinstance(events[-1], RunFailed)
    assert events[-1].code == "RUN_TIMEOUT"
    assert await store.load_state("s1") == {"prompts": ["earlier"]}


class CountInput(ToolInput):
    n: int


@tool()
async def count(args: CountInput) -> str:
    """Count."""
    return str(args.n)


async def test_tool_input_is_strict_json_like_the_agent_sdk_schema_check() -> None:
    backend = ScriptedBackend(
        {
            "main_agent": [
                ScriptedTurn(
                    tool_calls=[("count", {"n": 3}), ("count", {"n": "3"}), ("count", {"n": 3.0})]
                )
            ]
        }
    )
    events = await collect(
        Runner({"scripted": backend}, InMemorySessionStore()), spec(tools=(count,))
    )

    assert [r.is_error for r in events if isinstance(r, ToolResult)] == [False, True, False]


async def test_parallel_delegations_to_one_subagent_get_distinct_agent_paths() -> None:
    researcher = AgentSpec(name="researcher", description="r", model="m2", instructions=("r",))
    parent = spec(tools=(), subagents=(researcher,), context=ContextPolicy(compact_at_tokens=None))
    calls = [("delegate_to_researcher", {"task": "a"}), ("delegate_to_researcher", {"task": "b"})]
    backend = ScriptedBackend(
        {"main_agent": [ScriptedTurn(tool_calls=calls)], "researcher": [ScriptedTurn(text="x")]}
    )
    events = await collect(Runner({"scripted": backend}, InMemorySessionStore()), parent)

    paths = {e.agent for e in events if e.type == "turn.started" and e.agent != "main"}
    assert paths == {"main/researcher#call_main_agent_1_0", "main/researcher#call_main_agent_1_1"}


async def test_gather_all_cancels_siblings_when_one_fails() -> None:
    finished: list[str] = []

    async def slow() -> str:
        await asyncio.sleep(0.05)
        finished.append("slow")
        return "slow"

    async def failing() -> str:
        raise BackendError("UPSTREAM_RATE_LIMITED", "busy")

    with pytest.raises(BackendError):
        await gather_all(slow(), failing())
    await asyncio.sleep(0.1)

    assert finished == []


async def test_closing_the_stream_under_anyio_lets_backend_cleanup_finish() -> None:
    cleaned: list[int] = []
    entered = asyncio.Event()

    class Hanging(ScriptedBackend):
        async def run(
            self, ctx: RunContext, prompt: str, state: SessionState | None
        ) -> BackendResult:
            entered.set()
            try:
                await asyncio.sleep(10)
            finally:
                # Several awaits, like closing a CLI process or a stream.
                for step in range(3):
                    await asyncio.sleep(0)
                    cleaned.append(step)
            raise AssertionError("unreachable")

    runner = Runner({"scripted": Hanging({})}, InMemorySessionStore())

    async def consume() -> None:
        async for _ in runner.stream(spec=spec(), prompt="p", backend="scripted", session_id="s"):
            pass

    async with anyio.create_task_group() as group:  # how sse-starlette cancels on disconnect
        group.start_soon(consume)
        await entered.wait()
        group.cancel_scope.cancel()

    assert cleaned == [0, 1, 2]
