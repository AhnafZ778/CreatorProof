"""Webhook subscription management.

The signing secret is returned once at registration. Receivers verify
``HMAC-SHA256(secret, "<timestamp>.<body>")`` and reject timestamps outside the
replay window.
"""

import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_container, get_db, require_scope
from app.container import Container
from app.core.security import AuthContext
from app.domain.platform import CredentialScope
from app.models import WebhookDelivery, WebhookEndpoint
from app.schemas import (
    WebhookDeliveryRead,
    WebhookEndpointCreatedRead,
    WebhookEndpointCreateRequest,
    WebhookEndpointRead,
)
from app.services.webhooks import (
    CORRELATION_HEADER,
    DELIVERY_HEADER,
    EVENT_HEADER,
    EVENT_REVIEW_CASE_OPENED,
    EVENT_SCAN_COMPLETED,
    EVENT_STATEMENT_STATUS_CHANGED,
    SIGNATURE_HEADER,
    TIMESTAMP_HEADER,
)

router = APIRouter(prefix="/v1/webhooks", tags=["webhooks"])

SUPPORTED_EVENTS = [
    EVENT_SCAN_COMPLETED,
    EVENT_REVIEW_CASE_OPENED,
    EVENT_STATEMENT_STATUS_CHANGED,
]


@router.post("/endpoints", response_model=WebhookEndpointCreatedRead, status_code=201)
def create_endpoint(
    payload: WebhookEndpointCreateRequest,
    auth: Annotated[AuthContext, Depends(require_scope(CredentialScope.ADMIN))],
    db: Annotated[Session, Depends(get_db)],
    container: Annotated[Container, Depends(get_container)],
) -> WebhookEndpointCreatedRead:
    unsupported = [item for item in payload.event_types if item not in SUPPORTED_EVENTS]
    if unsupported:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "UNSUPPORTED_EVENT_TYPE",
                "unsupported": unsupported,
                "supported": SUPPORTED_EVENTS,
            },
        )
    secret = secrets.token_urlsafe(32)
    endpoint = WebhookEndpoint(
        tenant_id=auth.tenant_id,
        url=str(payload.url),
        secret=secret,
        event_types=payload.event_types or SUPPORTED_EVENTS,
    )
    db.add(endpoint)
    db.commit()
    db.refresh(endpoint)
    return WebhookEndpointCreatedRead(
        endpoint=WebhookEndpointRead.model_validate(endpoint),
        signing_secret=secret,
        verification={
            "algorithm": "HMAC-SHA256",
            "signed_value": "<timestamp>.<raw_request_body>",
            "signature_header": SIGNATURE_HEADER,
            "timestamp_header": TIMESTAMP_HEADER,
            "delivery_header": DELIVERY_HEADER,
            "event_header": EVENT_HEADER,
            "correlation_header": CORRELATION_HEADER,
            "signature_format": "v1=<hex digest>",
            "replay_window_seconds": container.settings.webhook_replay_window_seconds,
            "guidance": (
                "Reject a delivery whose timestamp is outside the replay window and "
                "treat repeated delivery ids as duplicates."
            ),
        },
    )


@router.get("/endpoints", response_model=list[WebhookEndpointRead])
def list_endpoints(
    auth: Annotated[AuthContext, Depends(require_scope(CredentialScope.ADMIN))],
    db: Annotated[Session, Depends(get_db)],
) -> list[WebhookEndpoint]:
    return list(
        db.scalars(
            select(WebhookEndpoint)
            .where(WebhookEndpoint.tenant_id == auth.tenant_id)
            .order_by(WebhookEndpoint.created_at)
        ).all()
    )


@router.delete("/endpoints/{endpoint_id}", status_code=status.HTTP_204_NO_CONTENT)
def deactivate_endpoint(
    endpoint_id: str,
    auth: Annotated[AuthContext, Depends(require_scope(CredentialScope.ADMIN))],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    endpoint = db.get(WebhookEndpoint, endpoint_id)
    if endpoint is None or endpoint.tenant_id != auth.tenant_id:
        raise HTTPException(status_code=404, detail="Webhook endpoint not found")
    endpoint.active = False
    db.commit()


@router.get("/deliveries", response_model=list[WebhookDeliveryRead])
def list_deliveries(
    auth: Annotated[AuthContext, Depends(require_scope(CredentialScope.ADMIN))],
    db: Annotated[Session, Depends(get_db)],
    state: Annotated[str | None, Query(max_length=40)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[WebhookDelivery]:
    query = select(WebhookDelivery).where(WebhookDelivery.tenant_id == auth.tenant_id)
    if state:
        query = query.where(WebhookDelivery.state == state)
    return list(db.scalars(query.order_by(WebhookDelivery.created_at.desc()).limit(limit)).all())
