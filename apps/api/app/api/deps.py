from collections.abc import Iterator
from typing import Annotated

from fastapi import Header, Request
from sqlalchemy.orm import Session

from app.container import Container
from app.core.security import require_tenant


def get_container(request: Request) -> Container:
    return request.app.state.container


def get_db(request: Request) -> Iterator[Session]:
    container: Container = request.app.state.container
    db = container.database.session_factory()
    try:
        yield db
    finally:
        db.close()


def get_tenant_id(
    request: Request,
    x_api_key: Annotated[str, Header(alias="X-API-Key")],
) -> str:
    return require_tenant(request, x_api_key)
