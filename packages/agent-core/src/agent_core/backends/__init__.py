"""Backend adapters. Each translates one native runtime into `AgentEvent`s and nothing else."""

from agent_core.backends.agent_sdk import AgentSdkBackend
from agent_core.backends.managed import ManagedBackend
from agent_core.backends.messages import MessagesBackend

__all__ = ["AgentSdkBackend", "ManagedBackend", "MessagesBackend"]
