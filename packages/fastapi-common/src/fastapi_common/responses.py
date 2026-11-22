"""Success envelope + pagination — same shape as the NestJS template.

FastAPI has no global response interceptor that keeps OpenAPI types, so handlers return
`ok(data)` explicitly and declare `-> StandardResponse[T]`.
"""

from http import HTTPStatus
from math import ceil

from fastapi import Query
from pydantic import BaseModel

from fastapi_common.context import elapsed_ms


class StandardResponse[T](BaseModel):
    data: T
    statusCode: int = 200
    statusMessage: str = "OK"
    spendTime: str


def ok[T](data: T, status_code: int = 200) -> StandardResponse[T]:
    return StandardResponse(
        data=data,
        statusCode=status_code,
        statusMessage=HTTPStatus(status_code).phrase,
        spendTime=f"{elapsed_ms()}ms",
    )


class PageQuery(BaseModel):
    page: int = 1
    limit: int = 10

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.limit


def page_query(
    page: int = Query(default=1, ge=1, le=1_000_000), limit: int = Query(default=10, ge=1, le=100)
) -> PageQuery:
    return PageQuery(page=page, limit=limit)


class Pagination(BaseModel):
    total: int
    page: int
    limit: int
    totalPages: int
    isLast: bool


class Page[T](BaseModel):
    items: list[T]
    pagination: Pagination

    @classmethod
    def build(cls, items: list[T], total: int, query: PageQuery) -> Page[T]:
        total_pages = ceil(total / query.limit) if total else 0
        return cls(
            items=items,
            pagination=Pagination(
                total=total,
                page=query.page,
                limit=query.limit,
                totalPages=total_pages,
                isLast=query.page >= total_pages,
            ),
        )
