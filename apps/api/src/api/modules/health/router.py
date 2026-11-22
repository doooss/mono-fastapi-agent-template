from fastapi import APIRouter, Request
from pydantic import BaseModel

from fastapi_common import AppError, Database, StandardResponse, ok

router = APIRouter(tags=["health"])


class HealthOut(BaseModel):
    status: str
    db: str
    version: str


@router.get("/health")
async def health(request: Request) -> StandardResponse[HealthOut]:
    db: Database = request.app.state.db
    try:
        await db.ping()
    except Exception as exc:
        raise AppError(
            503,
            "SERVICE_UNAVAILABLE",
            "서비스를 일시적으로 사용할 수 없습니다.",
            f"db: {type(exc).__name__}",
        ) from exc
    return ok(HealthOut(status="ok", db="up", version=request.app.version))
