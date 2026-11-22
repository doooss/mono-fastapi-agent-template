from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from api.settings import BackendName


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input: str = Field(min_length=1, max_length=20_000)
    session_id: str | None = Field(default=None, max_length=32)
    backend: BackendName | None = None
    """Defaults to AGENT_BACKEND. A session keeps the backend it started with."""


class AgentOut(BaseModel):
    name: str
    description: str
    model: str
    tools: list[str]
    subagents: list[str]


class RunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    session_id: str
    status: str
    prompt: str
    output: str | None
    stop_reason: str | None
    error_code: str | None
    turns: int
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    duration_ms: int | None
    created_at: datetime
    completed_at: datetime | None


class RunEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    seq: int
    type: str
    agent: str
    ts: float
    payload: dict[str, Any]
