from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Float, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from fastapi_common import Base, IdMixin, TimestampMixin, UTCDateTime


class AgentSession(IdMixin, TimestampMixin, Base):
    """A conversation pinned to one agent and one backend (backend state is not portable)."""

    __tablename__ = "agent_sessions"

    agent: Mapped[str] = mapped_column(String(48))
    backend: Mapped[str] = mapped_column(String(16))
    title: Mapped[str] = mapped_column(String(100))
    # Backend continuation: Messages history · Agent SDK session id · Managed session id.
    state: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)


class AgentRun(IdMixin, TimestampMixin, Base):
    __tablename__ = "agent_runs"
    __table_args__ = (
        # One running run per session — the DB enforces it across instances.
        Index(
            "uq_agent_runs_running_session",
            "session_id",
            unique=True,
            sqlite_where=text("status = 'running'"),
            postgresql_where=text("status = 'running'"),
        ),
    )

    session_id: Mapped[str] = mapped_column(
        ForeignKey("agent_sessions.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(16))  # running | completed | failed | cancelled
    prompt: Mapped[str] = mapped_column(Text)
    output: Mapped[str | None] = mapped_column(Text, nullable=True)
    stop_reason: Mapped[str | None] = mapped_column(String(16), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    turns: Mapped[int] = mapped_column(Integer, default=0)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_read_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_write_tokens: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class AgentRunEvent(Base):
    """Every event except text.delta — a backend-neutral replay of the run."""

    __tablename__ = "agent_run_events"

    run_id: Mapped[str] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="CASCADE"), primary_key=True
    )
    seq: Mapped[int] = mapped_column(Integer, primary_key=True)
    type: Mapped[str] = mapped_column(String(32))
    # Nested delegation paths (`main/<name>#<call_id>/…`) have no fixed bound.
    agent: Mapped[str] = mapped_column(Text)
    ts: Mapped[float] = mapped_column(Float)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
