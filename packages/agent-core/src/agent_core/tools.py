"""Tool definitions — one format, exported to every backend.

The template ships no tools. Add one with `@tool` on an async function that takes a single
pydantic model and returns text; register it in an `AgentSpec(tools=...)`.
"""

import inspect
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal, get_type_hints

from pydantic import BaseModel, ConfigDict

ToolKind = Literal["tool", "subagent"]

# 64-char API limit minus the Agent SDK's `mcp__app__` prefix.
TOOL_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]{1,54}$")


def delegate_tool_name(agent_name: str) -> str:
    """Name of the tool a parent agent calls to hand a task to the subagent `agent_name`."""
    return f"delegate_to_{agent_name}"


class ToolInput(BaseModel):
    """Base for tool inputs.

    Validated as strict JSON, nested models included (`"5"` is not an int), matching the JSON
    Schema check the Agent SDK applies before a call — so a bad input fails the same way on
    every backend. Unknown fields are rejected so model typos surface as tool errors.
    """

    model_config = ConfigDict(extra="forbid", strict=True)


@dataclass(frozen=True, kw_only=True)
class ToolSpec:
    name: str
    description: str
    input_model: type[BaseModel]
    handler: Callable[[Any], Awaitable[str]]
    # None = LoopPolicy.tool_timeout_s. Subagent delegation has no timeout (its loop is bounded).
    timeout_s: float | None = None
    kind: ToolKind = "tool"

    def __post_init__(self) -> None:
        if not TOOL_NAME_RE.fullmatch(self.name):
            raise ValueError(f"tool name must match {TOOL_NAME_RE.pattern}: {self.name!r}")

    def input_schema(self) -> dict[str, Any]:
        return self.input_model.model_json_schema()


def tool[M: BaseModel](
    *, name: str | None = None, description: str | None = None, timeout_s: float | None = None
) -> Callable[[Callable[[M], Awaitable[str]]], ToolSpec]:
    """`@tool()` over `async def search(args: SearchInput) -> str` (docstring = description)."""

    def wrap(fn: Callable[[M], Awaitable[str]]) -> ToolSpec:
        params = list(inspect.signature(fn).parameters)
        hints = get_type_hints(fn)
        model = hints.get(params[0]) if len(params) == 1 else None
        if not (isinstance(model, type) and issubclass(model, BaseModel)):
            raise TypeError(f"{fn.__name__}: tool takes exactly one pydantic model argument")
        doc = description or inspect.getdoc(fn)
        if not doc:
            raise TypeError(f"{fn.__name__}: tool needs a description (docstring)")
        return ToolSpec(
            name=name or fn.__name__,
            description=doc,
            input_model=model,
            handler=fn,
            timeout_s=timeout_s,
        )

    return wrap
