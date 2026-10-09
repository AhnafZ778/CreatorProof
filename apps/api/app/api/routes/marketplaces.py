"""Discovery connectors for image sources and eBay listings."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_container, get_db, require_scope
from app.api.routes.scans import _create_scan_bytes
from app.container import Container
from app.core.security import AuthContext
from app.domain.platform import CredentialScope
from app.schemas import (
    MarketplaceCandidateRead,
    MarketplaceProviderRead,
    MarketplaceScanRead,
    MarketplaceScanRequest,
    MarketplaceSearchRead,
    MarketplaceSearchRequest,
    ScanRead,
)
from app.services.marketplaces import MarketplaceError

router = APIRouter(prefix="/v1/marketplaces", tags=["marketplaces"])


def _provider_error(exc: MarketplaceError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": str(exc)},
    )


@router.get("/providers", response_model=list[MarketplaceProviderRead])
def provider_statuses(
    auth: Annotated[AuthContext, Depends(require_scope(CredentialScope.SCANS_WRITE))],
    container: Annotated[Container, Depends(get_container)],
) -> list[dict]:
    """Safe configuration status; never return credentials or mint tokens."""
    return container.marketplaces.provider_statuses()


@router.post("/search", response_model=MarketplaceSearchRead)
async def search_marketplace(
    payload: MarketplaceSearchRequest,
    auth: Annotated[AuthContext, Depends(require_scope(CredentialScope.SCANS_WRITE))],
    container: Annotated[Container, Depends(get_container)],
) -> MarketplaceSearchRead:
    """Search a provider and persist short-lived source observations."""
    per_page = min(payload.per_page, container.settings.marketplace_max_results)
    try:
        results = await container.marketplaces.search(
            payload.provider, query=payload.query, page=payload.page, per_page=per_page
        )
        observations = [
            container.marketplaces.observe(
                auth.tenant_id,
                row,
                search={"query": payload.query.strip(), "page": payload.page},
            )
            for row in results
        ]
    except MarketplaceError as exc:
        raise _provider_error(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return MarketplaceSearchRead(
        provider=payload.provider,
        query=payload.query.strip(),
        page=payload.page,
        per_page=per_page,
        results=[MarketplaceCandidateRead.model_validate(row) for row in observations],
    )


@router.post("/scan", response_model=MarketplaceScanRead, status_code=status.HTTP_202_ACCEPTED)
async def scan_marketplace_result(
    payload: MarketplaceScanRequest,
    auth: Annotated[AuthContext, Depends(require_scope(CredentialScope.SCANS_WRITE))],
    db: Annotated[Session, Depends(get_db)],
    container: Annotated[Container, Depends(get_container)],
) -> MarketplaceScanRead:
    """Download one observed image and send it through the normal scan pipeline."""
    try:
        observation = container.marketplaces.load_observation(
            auth.tenant_id, payload.observation_id
        )
        raw = await container.marketplaces.download(observation)
        scan = _create_scan_bytes(
            raw=raw,
            catalog_id=payload.catalog_id,
            intended_use=payload.intended_use,
            idempotency_key=f"marketplace:{payload.observation_id}:{payload.catalog_id}"[:160],
            auth=auth,
            db=db,
            container=container,
            source_observation=observation,
            country_code=payload.country_code,
            use_context=payload.use_context.model_dump(exclude_none=True)
            if payload.use_context
            else None,
        )
    except MarketplaceError as exc:
        raise _provider_error(exc) from exc
    return MarketplaceScanRead(
        provider=observation["provider"],
        selected=MarketplaceCandidateRead.model_validate(observation),
        scan=ScanRead.model_validate(scan),
    )
