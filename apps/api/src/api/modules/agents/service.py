from collections.abc import AsyncIterator, Mapping
from datetime import timedelta
from typing import Any

import anyio
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from agent_core import (
    TERMINAL_EVENTS,
    AgentEvent,
    AgentSpec,
    RunCompleted,
    RunFailed,
    Runner,
    SessionState,
    TextDelta,
)
from api.modules.agents.models import AgentRun, AgentRunEvent, AgentSession
from api.modules.agents.schemas import RunRequest
from fastapi_common import AppError, Database, Page, PageQuery, utcnow

_ENVELOPE = {"run_id", "seq", "ts", "agent", "type"}


class SqlSessionStore:
    """agent_core SessionStore on `agent_sessions.state`."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def load_state(self, session_id: str) -> SessionState | None:
        async with self._db.sessions() as session:
            row = await session.get(AgentSession, session_id)
            return row.state if row else None

    async def save_state(self, session_id: str, state: SessionState | None) -> None:
        async with self._db.sessions() as session, session.begin():
            await session.execute(
                update(AgentSession)
                .where(AgentSession.id == session_id)
                .values(state=state, updated_at=utcnow())
            )


class AgentRunService:
    def __init__(
        self,
        db: Database,
        runner: Runner,
        agents: Mapping[str, AgentSpec],
        default_backend: str,
    ) -> None:
        self._db = db
        self._runner = runner
        self.agents = dict(agents)
        self._default_backend = default_backend

    def get_spec(self, name: str) -> AgentSpec:
        spec = self.agents.get(name)
        if spec is None:
            raise AppError(404, "AGENT_NOT_FOUND", "에이전트를 찾을 수 없습니다.", f"agent: {name}")
        return spec

    async def start(self, spec: AgentSpec, request: RunRequest) -> tuple[str, str, str]:
        """Create or check the session, then a running run -> (session_id, run_id, backend)."""
        async with self._db.sessions() as session:
            if request.session_id:
                row = await session.get(AgentSession, request.session_id)
                if row is None:
                    raise AppError(404, "SESSION_NOT_FOUND", "세션을 찾을 수 없습니다.")
                if row.agent != spec.name:
                    raise AppError(409, "SESSION_AGENT_MISMATCH", "다른 에이전트의 세션입니다.")
                if request.backend and request.backend != row.backend:
                    raise AppError(
                        409,
                        "SESSION_BACKEND_MISMATCH",
                        f"이 세션은 {row.backend} 백엔드로 시작되었습니다.",
                    )
                backend = row.backend
            else:
                backend = request.backend or self._default_backend
                row = AgentSession(agent=spec.name, backend=backend, title=request.input[:50])
                session.add(row)
            if backend not in self._runner.backend_names:
                raise AppError(
                    400, "BACKEND_NOT_AVAILABLE", "사용할 수 없는 백엔드입니다.", backend
                )
            await session.commit()
            session_id = row.id
        return session_id, await self._insert_run(session_id, request.input), backend

    async def _insert_run(self, session_id: str, prompt: str) -> str:
        for attempt in range(2):
            async with self._db.sessions() as session:
                run = AgentRun(session_id=session_id, status="running", prompt=prompt)
                session.add(run)
                try:
                    await session.commit()
                    return run.id
                except IntegrityError:
                    await session.rollback()
            if attempt == 0 and await self._reap_stale_run(session_id):
                continue
            break
        raise AppError(409, "RUN_IN_PROGRESS", "이 세션에서 이미 실행 중인 요청이 있습니다.")

    async def _reap_stale_run(self, session_id: str) -> bool:
        """Fail a `running` run its process can no longer own (older than 2x the run timeout)."""
        timeout = self._runner.run_timeout_s
        if timeout is None:
            return False
        cutoff = utcnow() - timedelta(seconds=timeout * 2)
        async with self._db.sessions() as session, session.begin():
            result = await session.execute(
                update(AgentRun)
                .where(
                    AgentRun.session_id == session_id,
                    AgentRun.status == "running",
                    AgentRun.created_at < cutoff,
                )
                .values(
                    status="failed",
                    error_code="RUN_INTERRUPTED",
                    completed_at=utcnow(),
                    updated_at=utcnow(),
                )
            )
            return bool(getattr(result, "rowcount", 0))

    async def stream(
        self, *, spec: AgentSpec, session_id: str, run_id: str, backend: str, prompt: str
    ) -> AsyncIterator[AgentEvent]:
        final: AgentEvent | None = None
        recorded: list[AgentRunEvent] = []
        try:
            async for event in self._runner.stream(
                spec=spec, prompt=prompt, backend=backend, session_id=session_id, run_id=run_id
            ):
                if not isinstance(event, TextDelta):
                    recorded.append(
                        AgentRunEvent(
                            run_id=run_id,
                            seq=event.seq,
                            type=event.type,
                            agent=event.agent,
                            ts=event.ts,
                            payload=event.model_dump(mode="json", exclude=_ENVELOPE),
                        )
                    )
                if event.type in TERMINAL_EVENTS:
                    final = event
                yield event
        finally:
            # Runs on client disconnect too; shield so the cancelled stream still records the run.
            with anyio.CancelScope(shield=True):
                await self._finish(run_id, final, recorded)

    async def _finish(
        self, run_id: str, final: AgentEvent | None, recorded: list[AgentRunEvent]
    ) -> None:
        values: dict[str, Any] = {"completed_at": utcnow(), "updated_at": utcnow()}
        match final:
            case RunCompleted():
                values |= {
                    "status": "completed",
                    "stop_reason": final.stop_reason,
                    "output": final.output,
                    "turns": final.turns,
                    "duration_ms": final.duration_ms,
                    "input_tokens": final.usage.input_tokens,
                    "output_tokens": final.usage.output_tokens,
                    "cache_read_tokens": final.usage.cache_read_tokens,
                    "cache_write_tokens": final.usage.cache_write_tokens,
                }
            case RunFailed():
                values |= {"status": "failed", "error_code": final.code}
            case _:
                values |= {"status": "cancelled", "stop_reason": "cancelled"}
        async with self._db.sessions() as session, session.begin():
            await session.execute(
                update(AgentRun)
                .where(AgentRun.id == run_id, AgentRun.status == "running")
                .values(**values)
            )
            session.add_all(recorded)

    async def get_run(self, run_id: str) -> AgentRun:
        async with self._db.sessions() as session:
            run = await session.get(AgentRun, run_id)
            if run is None:
                raise AppError(404, "RUN_NOT_FOUND", "실행 기록을 찾을 수 없습니다.")
            return run

    async def list_runs(self, session_id: str, query: PageQuery) -> Page[AgentRun]:
        async with self._db.sessions() as session:
            if await session.get(AgentSession, session_id) is None:
                raise AppError(404, "SESSION_NOT_FOUND", "세션을 찾을 수 없습니다.")
            where = AgentRun.session_id == session_id
            total = await session.scalar(select(func.count()).select_from(AgentRun).where(where))
            rows = await session.scalars(
                select(AgentRun)
                .where(where)
                .order_by(AgentRun.created_at.desc())
                .offset(query.offset)
                .limit(query.limit)
            )
            return Page.build(list(rows), total or 0, query)

    async def list_events(self, run_id: str) -> list[AgentRunEvent]:
        await self.get_run(run_id)
        async with self._db.sessions() as session:
            rows = await session.scalars(
                select(AgentRunEvent)
                .where(AgentRunEvent.run_id == run_id)
                .order_by(AgentRunEvent.seq)
            )
            return list(rows)
