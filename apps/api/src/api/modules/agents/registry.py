"""Agents this app serves. Replace the examples with your own specs.

The template ships no tools — add `@tool` functions to `AgentSpec(tools=...)`.
"""

from agent_core import AgentSpec, LoopPolicy
from api.settings import Settings

ROLE = """You are a helpful assistant for this service.
Answer directly. When a question needs focused investigation, delegate it to the researcher
with a self-contained task, then combine its findings into your answer."""

STYLE = """Reply in the user's language. Keep answers short and structured.
Say plainly when you do not know something instead of guessing."""

RESEARCHER = """You investigate one focused question and report findings.
State what you are confident about and what remains uncertain. No preamble."""


def build_agents(settings: Settings) -> dict[str, AgentSpec]:
    researcher = AgentSpec(
        name="researcher",
        description="Investigates one focused question and reports findings with uncertainty.",
        model=settings.SUBAGENT_MODEL,
        instructions=(RESEARCHER,),
        loop=LoopPolicy(max_turns=10),
    )
    assistant = AgentSpec(
        name="assistant",
        description="General assistant that can delegate focused research.",
        model=settings.AGENT_MODEL,
        instructions=(ROLE, STYLE),
        subagents=(researcher,),
    )
    return {spec.name: spec for spec in (assistant,)}
