from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import __version__
from app.api.routes import (
    credentials,
    health,
    network,
    policies,
    proof,
    review,
    rights,
    scans,
    usage,
    webhooks,
    works,
)
from app.container import Container, build_container, initialize_database
from app.core.config import Settings, get_settings
from app.middleware import CorrelationMiddleware, RateLimitMiddleware, TokenBucketLimiter
from app.observability import configure_logging


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or get_settings()
    configure_logging(resolved_settings.log_format)
    container: Container = build_container(resolved_settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        from app.services.scan_runner import recover_orphaned_scans

        initialize_database(container)
        app.state.container = container
        # Work accepted before a crash is re-published before new traffic arrives,
        # so an API or worker restart cannot strand a scan.
        recover_orphaned_scans(container)
        container.start_background_workers()
        try:
            yield
        finally:
            container.stop_background_workers()
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
    app.add_middleware(
        RateLimitMiddleware,
        limiter=TokenBucketLimiter(
            requests_per_minute=resolved_settings.rate_limit_requests_per_minute,
            burst=resolved_settings.rate_limit_burst,
        ),
    )
    app.add_middleware(CorrelationMiddleware)
    app.include_router(health.router)
    app.include_router(works.router)
    app.include_router(scans.router)
    app.include_router(rights.router)
    app.include_router(policies.router)
    app.include_router(review.router)
    app.include_router(credentials.router)
    app.include_router(webhooks.router)
    app.include_router(proof.router)
    app.include_router(network.router)
    app.include_router(usage.router)
    return app


app = create_app()
