"""Swagger `/api` · OpenAPI `/api-json` · ReDoc `/docs`, all behind basic auth.

Create the app with `docs_url=None, redoc_url=None, openapi_url=None` and call `mount_docs`.
"""

import secrets
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

_basic = HTTPBasic(auto_error=False)


def mount_docs(app: FastAPI, *, user: str, password: str, title: str) -> None:
    def require_auth(
        credentials: Annotated[HTTPBasicCredentials | None, Depends(_basic)],
    ) -> None:
        valid = credentials is not None and (
            secrets.compare_digest(credentials.username.encode(), user.encode())
            & secrets.compare_digest(credentials.password.encode(), password.encode())
        )
        if not valid:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Unauthorized",
                headers={"WWW-Authenticate": "Basic"},
            )

    guard = [Depends(require_auth)]

    @app.get("/api-json", include_in_schema=False, dependencies=guard)
    async def openapi() -> dict[str, Any]:
        return app.openapi()

    @app.get("/api", include_in_schema=False, dependencies=guard)
    async def swagger() -> HTMLResponse:
        return get_swagger_ui_html(openapi_url="/api-json", title=f"{title} API")

    @app.get("/docs", include_in_schema=False, dependencies=guard)
    async def redoc() -> HTMLResponse:
        return get_redoc_html(openapi_url="/api-json", title=f"{title} API")
