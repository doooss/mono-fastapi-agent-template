"""Claude Agent SDK backend — the loop runs in the bundled Claude Code CLI.

Everything Claude Code would add on its own is switched off so the model sees exactly what the
other backends send: `tools=[]` (no built-in tools), a plain-string system prompt (replaces the
Claude Code prompt), `setting_sources=[]` (no CLAUDE.md / user settings). Our tools run
in-process through an SDK MCP server and go through `RunContext.execute_tool` like everywhere else.

Session state = the CLI session id (`resume`). Transcripts live under the CLI's config dir on
this machine, so a session can only be resumed on the instance that created it.
"""

import asyncio
import json
import logging
import uuid
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ClaudeSDKError,
    ResultMessage,
    SdkMcpTool,
    StreamEvent,
    SystemMessage,
    ToolAnnotations,
    ToolUseBlock,
    create_sdk_mcp_server,
    get_session_messages,
)
from claude_agent_sdk import tool as sdk_tool

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
from agent_core.tools import ToolSpec

logger = logging.getLogger("agent_core.backends.agent_sdk")

SERVER = "app"
TOOL_PREFIX = f"mcp__{SERVER}__"
CLAIM_TIMEOUT_S = 30.0


def _usage(raw: dict[str, Any], base: Usage | None = None) -> Usage:
    current = base or Usage()
    return Usage(
        input_tokens=raw.get("input_tokens") or current.input_tokens,
        output_tokens=raw.get("output_tokens") or current.output_tokens,
        cache_read_tokens=raw.get("cache_read_input_tokens") or current.cache_read_tokens,
        cache_write_tokens=raw.get("cache_creation_input_tokens") or current.cache_write_tokens,
    )


class StreamTranslator:
    """Raw API stream events (via `include_partial_messages`) -> turn / text events."""

    def __init__(self, model: str) -> None:
        self.model = model
        self.turn = 0
        self.turn_open = False
        self._usage = Usage()
        self._stop: str | None = None

    def on_event(self, event: dict[str, Any]) -> list[AgentEvent]:
        match event.get("type"):
            case "message_start":
                self.turn += 1
                self.turn_open = True
                self._usage = _usage(event.get("message", {}).get("usage") or {})
                self._stop = None
                return [TurnStarted(turn=self.turn, model=self.model)]
            case "content_block_delta":
                delta = event.get("delta", {})
                if delta.get("type") == "text_delta" and delta.get("text"):
                    return [TextDelta(text=delta["text"])]
            case "message_delta":
                self._usage = _usage(event.get("usage") or {}, self._usage)
                self._stop = (event.get("delta") or {}).get("stop_reason") or self._stop
            case "message_stop" if self.turn_open:
                self.turn_open = False
                return [TurnCompleted(turn=self.turn, stop_reason=self._stop, usage=self._usage)]
            case _:
                pass
        return []


def result_stop_reason(result: ResultMessage) -> StopReason:
    """Map the CLI's final result. API failures arrive as `subtype="success", is_error=True`."""
    if result.is_error:
        logger.warning(
            "agent sdk run failed",
            extra={
                "subtype": result.subtype,
                "api_error_status": result.api_error_status,
                "errors": result.errors,
            },
        )
        status = result.api_error_status or 0
        if result.subtype == "error_max_turns":
            return "max_turns"
        if result.subtype == "error_max_budget_usd":
            return "budget"
        if status == 429:
            raise BackendError("UPSTREAM_RATE_LIMITED", "요청이 많아 잠시 후 다시 시도해 주세요.")
        if status >= 500:
            raise BackendError(
                "UPSTREAM_UNAVAILABLE", "모델 서비스에 일시적으로 연결할 수 없습니다."
            )
        if status:
            raise BackendError("UPSTREAM_ERROR", "모델 호출에 실패했습니다.")
        raise BackendError("AGENT_RUN_FAILED", "에이전트 실행 중 오류가 발생했습니다.")
    match result.subtype:
        case "error_max_turns":
            return "max_turns"
        case "error_max_budget_usd":
            return "budget"
        case _:
            return "refusal" if result.stop_reason == "refusal" else "end_turn"


class CallIds:
    """Maps an in-process MCP call back to the model's tool_use id.

    SDK tool handlers receive only the arguments. The tool_use block reaches the message stream
    first, so the consumer `offer`s (name, args) -> id and the handler `claim`s it.
    """

    def __init__(self) -> None:
        self._ids: defaultdict[str, deque[str]] = defaultdict(deque)
        self._changed = asyncio.Condition()

    @staticmethod
    def _key(name: str, args: dict[str, Any]) -> str:
        return f"{name}:{json.dumps(args, sort_keys=True, ensure_ascii=False)}"

    async def offer(self, name: str, args: dict[str, Any], call_id: str) -> None:
        async with self._changed:
            self._ids[self._key(name, args)].append(call_id)
            self._changed.notify_all()

    async def claim(self, name: str, args: dict[str, Any]) -> str:
        key = self._key(name, args)
        try:
            async with self._changed:
                await asyncio.wait_for(
                    self._changed.wait_for(lambda: bool(self._ids[key])), CLAIM_TIMEOUT_S
                )
                return self._ids[key].popleft()
        except TimeoutError:
            logger.warning("tool call id not found in stream", extra={"tool": name})
            return f"sdk_{uuid.uuid4().hex}"


class AgentSdkBackend:
    name = "agent_sdk"

    def __init__(self, *, api_key: str | None, workdir: Path) -> None:
        self._env = {"ANTHROPIC_API_KEY": api_key} if api_key else {}
        self._workdir = workdir

    async def run(self, ctx: RunContext, prompt: str, state: SessionState | None) -> BackendResult:
        spec = ctx.spec
        call_ids = CallIds()
        fatal: list[BackendError] = []
        tools = [self._sdk_tool(ctx, t, call_ids, fatal) for t in ctx.tools.values()]
        self._workdir.mkdir(parents=True, exist_ok=True)
        resume = (state or {}).get("sdk_session_id")
        if resume and not await asyncio.to_thread(self._transcript_exists, resume):
            # Transcripts are local to the CLI config dir: another instance or a restarted
            # container cannot continue this session.
            raise BackendError(
                "SESSION_STATE_LOST",
                "이전 대화 기록을 찾을 수 없습니다. 새 세션으로 시작해 주세요.",
            )
        options = ClaudeAgentOptions(
            model=spec.model,
            system_prompt=system_prompt(spec),
            tools=[],
            mcp_servers={SERVER: create_sdk_mcp_server(name=SERVER, tools=tools)} if tools else {},
            allowed_tools=[TOOL_PREFIX + name for name in ctx.tools],
            permission_mode="dontAsk",
            # Isolation: no CLAUDE.md / settings, no user-scope MCP servers, and the prompt is
            # sent as data — otherwise `@/path` would read local files and `/cmd` would run.
            setting_sources=[],
            strict_mcp_config=True,
            verbatim_prompts=True,
            max_turns=spec.loop.max_turns,
            include_partial_messages=True,
            resume=resume,
            cwd=self._workdir,
            env=self._env,
        )
        translator = StreamTranslator(spec.model)
        # Tool calls seen mid-turn are released only after turn.completed, matching the
        # event order of the other backends (turn.completed -> tool.call).
        held: list[ToolUseBlock] = []
        result: ResultMessage | None = None
        # `fatal`: the SDK turns handler exceptions into tool errors; a subagent's BackendError
        # must fail the run instead (as on the other backends), so handlers park it there.
        try:
            async with ClaudeSDKClient(options) as client:
                await client.query(prompt)
                async for message in client.receive_response():
                    if fatal:
                        raise fatal[0]
                    match message:
                        case StreamEvent() if message.parent_tool_use_id is None:
                            for event in translator.on_event(message.event):
                                await ctx.emit(event)
                            if not translator.turn_open:
                                for use in held:
                                    await call_ids.offer(
                                        use.name.removeprefix(TOOL_PREFIX), use.input, use.id
                                    )
                                held.clear()
                        case AssistantMessage():
                            for block in message.content:
                                if isinstance(block, ToolUseBlock) and block.name.startswith(
                                    TOOL_PREFIX
                                ):
                                    if translator.turn_open:
                                        held.append(block)
                                    else:
                                        await call_ids.offer(
                                            block.name.removeprefix(TOOL_PREFIX),
                                            block.input,
                                            block.id,
                                        )
                        case SystemMessage(subtype="compact_boundary"):
                            meta = message.data.get("compact_metadata") or {}
                            await ctx.emit(ContextCompacted(pre_tokens=meta.get("pre_tokens")))
                        case ResultMessage():
                            result = message
                        case _:
                            pass
        except ClaudeSDKError as exc:
            # Error results also end with a non-zero CLI exit; the ResultMessage already says why.
            if result is None:
                logger.warning("agent sdk failed", exc_info=exc)
                raise BackendError(
                    "UPSTREAM_UNAVAILABLE", "에이전트 런타임을 실행할 수 없습니다."
                ) from exc
        if fatal:
            raise fatal[0]
        if result is None:
            raise BackendError("AGENT_RUN_FAILED", "에이전트 실행이 결과 없이 끝났습니다.")
        return BackendResult(result_stop_reason(result), {"sdk_session_id": result.session_id})

    @staticmethod
    def _sdk_tool(
        ctx: RunContext, spec: ToolSpec, call_ids: CallIds, fatal: list[BackendError]
    ) -> SdkMcpTool[Any]:
        async def handler(args: dict[str, Any]) -> dict[str, Any]:
            call_id = await call_ids.claim(spec.name, args)
            try:
                outcome = await ctx.execute_tool(call_id, spec.name, args)
            except BackendError as exc:
                fatal.append(exc)
                return {"content": [{"type": "text", "text": exc.message}], "is_error": True}
            except Exception:
                # Only run-fatal errors escape execute_tool (e.g. a subagent run crashing).
                logger.exception("subagent run failed", extra={"tool": spec.name})
                failure = BackendError("AGENT_RUN_FAILED", "에이전트 실행 중 오류가 발생했습니다.")
                fatal.append(failure)
                # Never hand the exception text to the CLI: it would reach the model and transcript.
                return {"content": [{"type": "text", "text": failure.message}], "is_error": True}
            return {
                "content": [{"type": "text", "text": outcome.content}],
                "is_error": outcome.is_error,
            }

        # The CLI runs MCP tools in parallel only when marked read-only; the other backends always
        # run one turn's calls concurrently, so every tool is marked the same way here.
        return sdk_tool(
            spec.name,
            spec.description,
            spec.input_schema(),
            annotations=ToolAnnotations(readOnlyHint=True),
        )(handler)

    def _transcript_exists(self, session_id: str) -> bool:
        return bool(get_session_messages(session_id, directory=str(self._workdir), limit=1))
