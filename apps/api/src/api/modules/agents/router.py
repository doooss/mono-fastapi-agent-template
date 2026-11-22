from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sse_starlette import EventSourceResponse, ServerSentEvent

from api.modules.agents.schemas import AgentOut, RunEventOut, RunOut, RunRequest
from api.modules.agents.service import AgentRunService
from fastapi_common import Page, PageQuery, StandardResponse, ok, page_query

router = APIRouter(tags=["agents"])


def get_service(request: Request) -> AgentRunService:
    service: AgentRunService = request.app.state.agent_service
    return service


Service = Annotated[AgentRunService, Depends(get_service)]


@router.get("/agents")
async def list_agents(service: Service) -> StandardResponse[list[AgentOut]]:
    return ok(
        [
            AgentOut(
                name=spec.name,
                description=spec.description,
                model=spec.model,
                tools=[t.name for t in spec.tools],
                subagents=[s.name for s in spec.subagents],
            )
            for spec in service.agents.values()
        ]
    )


@router.post(
    "/agents/{name}/runs",
    response_class=EventSourceResponse,
    responses={200: {"content": {"text/event-stream": {}}, "description": "AgentEvent stream"}},
)
async def create_run(name: str, body: RunRequest, service: Service) -> EventSourceResponse:
    """Start a run and stream its events (SSE: `event` = type, `id` = seq, `data` = JSON).

    Validation errors are returned as a JSON error before the stream starts.
    """
    spec = service.get_spec(name)
    session_id, run_id, backend = await service.start(spec, body)

    async def events() -> AsyncIterator[ServerSentEvent]:
        async for event in service.stream(
            spec=spec, session_id=session_id, run_id=run_id, backend=backend, prompt=body.input
        ):
            yield ServerSentEvent(data=event.model_dump_json(), event=event.type, id=str(event.seq))

    return EventSourceResponse(
        events(), ping=15, headers={"x-session-id": session_id, "x-run-id": run_id}
    )


@router.get("/sessions/{session_id}/runs")
async def list_runs(
    session_id: str, service: Service, query: Annotated[PageQuery, Depends(page_query)]
) -> StandardResponse[Page[RunOut]]:
    page = await service.list_runs(session_id, query)
    return ok(
        Page[RunOut](
            items=[RunOut.model_validate(r) for r in page.items], pagination=page.pagination
        )
    )


@router.get("/runs/{run_id}")
async def get_run(run_id: str, service: Service) -> StandardResponse[RunOut]:
    return ok(RunOut.model_validate(await service.get_run(run_id)))


@router.get("/runs/{run_id}/events")
async def list_run_events(run_id: str, service: Service) -> StandardResponse[list[RunEventOut]]:
    return ok([RunEventOut.model_validate(e) for e in await service.list_events(run_id)])
