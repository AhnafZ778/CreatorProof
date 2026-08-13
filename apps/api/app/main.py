from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import __version__
from app.api.routes import health, scans, works
from app.container import Container, build_container, initialize_database
from app.core.config import Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or get_settings()
    container: Container = build_container(resolved_settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        initialize_database(container)
        app.state.container = container
        try:
            yield
        finally:
            if container.queue is not None:
                container.queue.close()

    app = FastAPI(
        title="CreatorProof API",
        version=__version__,
        description=(
            "Source-scoped creative-rights evidence API. Outputs are evidence "
            "and policy decisions, "
            "not legal infringement determinations."
        ),
        lifespan=lifespan,
    )
    app.state.container = container
    app.include_router(health.router)
    app.include_router(works.router)
    app.include_router(scans.router)
    return app


app = create_app()
