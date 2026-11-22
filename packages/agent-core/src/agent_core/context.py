"""Context engineering shared by every backend.

The model must see the same system prompt, tool surface and tool-output size regardless of
backend. Backends call these helpers; none of them builds prompts or descriptions on its own.
"""

from pydantic import Field

from agent_core.spec import AgentSpec
from agent_core.tools import ToolInput

DELEGATE_SUFFIX = (
    "\n\nThe subagent starts with an empty context and sees only `task`: "
    "include every fact, constraint and expected output format it needs. "
    "Returns the subagent's final answer."
)


class DelegateInput(ToolInput):
    task: str = Field(min_length=1, description="Complete, self-contained instructions.")


def system_prompt(spec: AgentSpec) -> str:
    return "\n\n".join(section.strip() for section in spec.instructions if section.strip())


def delegate_description(sub: AgentSpec) -> str:
    return sub.description.strip() + DELEGATE_SUFFIX


def clip(text: str, max_chars: int) -> str:
    """Cut oversized tool output and say so, so the model knows the result is partial."""
    if len(text) <= max_chars:
        return text
    return f"{text[:max_chars]}\n\n[truncated: {len(text) - max_chars} more characters omitted]"
