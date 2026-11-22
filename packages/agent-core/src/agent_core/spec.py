"""Backend-neutral agent definition."""

import re
from dataclasses import dataclass, field

from agent_core.tools import ToolSpec, delegate_tool_name

# `delegate_to_<name>` must still fit the tool name limit (54).
_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,41}$")
# Server-side compaction rejects triggers below this (Messages API).
MIN_COMPACTION_TOKENS = 50_000


@dataclass(frozen=True, kw_only=True)
class LoopPolicy:
    max_turns: int = 20
    """Model requests per agent run (each subagent run has its own budget)."""
    max_tokens: int = 8192
    """Output tokens per model request (Messages backend; the others decide themselves)."""
    tool_timeout_s: float = 60.0


@dataclass(frozen=True, kw_only=True)
class ContextPolicy:
    tool_result_max_chars: int = 20_000
    """Tool output beyond this is cut before the model sees it — same on every backend."""
    compact_at_tokens: int | None = 150_000
    """Server-side compaction trigger. Messages backend only — Agent SDK and Managed Agents
    compact on their own thresholds."""
    clear_tool_uses_at_tokens: int | None = None
    """Clear old tool results past this prompt size (Messages backend only)."""
    keep_tool_uses: int = 3

    def __post_init__(self) -> None:
        if self.compact_at_tokens is not None and self.compact_at_tokens < MIN_COMPACTION_TOKENS:
            raise ValueError(f"compact_at_tokens must be >= {MIN_COMPACTION_TOKENS}")
        if self.tool_result_max_chars < 1:
            raise ValueError("tool_result_max_chars must be positive")


@dataclass(frozen=True, kw_only=True)
class AgentSpec:
    name: str
    description: str
    """What this agent does. Shown to a parent agent as the delegation tool's description."""
    model: str
    instructions: tuple[str, ...]
    """System prompt sections, joined in order. Put stable text first so caching covers it."""
    tools: tuple[ToolSpec, ...] = ()
    subagents: tuple[AgentSpec, ...] = ()
    loop: LoopPolicy = field(default_factory=LoopPolicy)
    context: ContextPolicy = field(default_factory=ContextPolicy)

    def __post_init__(self) -> None:
        if not _NAME_RE.fullmatch(self.name):
            raise ValueError(f"agent name must match {_NAME_RE.pattern}: {self.name!r}")
        names = [t.name for t in self.tools] + [delegate_tool_name(s.name) for s in self.subagents]
        if len(names) != len(set(names)):
            raise ValueError(f"{self.name}: duplicate tool / subagent names")
