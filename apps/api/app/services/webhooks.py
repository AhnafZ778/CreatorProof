"""Signed outbound webhooks.

Each delivery carries a stable delivery id, a timestamp and an HMAC-SHA256
signature over ``timestamp.body``. Receivers reject a stale timestamp, so a
captured request cannot be replayed indefinitely. Failed deliveries retry with
exponential backoff and then dead-letter instead of retrying forever.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import logging
import socket
import threading
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.platform import WebhookDeliveryState
from app.observability import METRICS, current_correlation_id, log_event

logger = logging.getLogger("creatorproof.webhooks")

EVENT_SCAN_COMPLETED = "scan.completed"
EVENT_REVIEW_CASE_OPENED = "review_case.opened"
EVENT_STATEMENT_STATUS_CHANGED = "statement.status_changed"

SIGNATURE_HEADER = "X-CreatorProof-Signature"
TIMESTAMP_HEADER = "X-CreatorProof-Timestamp"
DELIVERY_HEADER = "X-CreatorProof-Delivery"
EVENT_HEADER = "X-CreatorProof-Event"
CORRELATION_HEADER = "X-CreatorProof-Correlation-Id"


def sign_payload(secret: str, timestamp: str, body: bytes) -> str:
    message = timestamp.encode("ascii") + b"." + body
    digest = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()
    return f"v1={digest}"


def verify_signature(
    secret: str,
    *,
    signature: str,
    timestamp: str,
    body: bytes,
    tolerance_seconds: int = 300,
) -> bool:
    """Reference verifier published for customers, and used by the test suite."""
    try:
        sent_at = datetime.fromtimestamp(int(timestamp), UTC)
    except (TypeError, ValueError):
        return False
    if abs((datetime.now(UTC) - sent_at).total_seconds()) > tolerance_seconds:
        return False
    return hmac.compare_digest(sign_payload(secret, timestamp, body), signature)


def _is_private_host(url: str) -> bool:
    host = urllib.parse.urlparse(url).hostname or ""
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return True
    for info in infos:
        try:
            address = ipaddress.ip_address(info[4][0])
        except ValueError:
            continue
        if address.is_private or address.is_loopback or address.is_link_local:
            return True
    return False


def queue_event(db: Session, *, tenant_id: str, event_type: str, payload: dict) -> int:
    """Fan an event out to every active subscriber for this tenant."""
    from app.models import WebhookDelivery, WebhookEndpoint

    endpoints = db.scalars(
        select(WebhookEndpoint).where(
            WebhookEndpoint.tenant_id == tenant_id, WebhookEndpoint.active.is_(True)
        )
    ).all()
    queued = 0
    for endpoint in endpoints:
        subscribed = endpoint.event_types or []
        if subscribed and event_type not in subscribed:
            continue
        db.add(
            WebhookDelivery(
                tenant_id=tenant_id,
                endpoint_id=endpoint.id,
                event_type=event_type,
                payload=payload,
                correlation_id=current_correlation_id(),
            )
        )
        queued += 1
    if queued:
        db.commit()
        METRICS.increment("creatorproof_webhook_queued_total", event_type=event_type, value=queued)
    return queued


def queue_scan_completed(db: Session, *, scan, packet: dict, statement, review_case_id) -> int:
    """Publish a result summary. Full evidence is fetched over the authenticated API."""
    proof = (packet or {}).get("proof") or {}
    scope = (packet or {}).get("scope") or {}
    payload = {
        "schema": "creatorproof.webhook.scan_completed.v1",
        "scan_id": scan.id,
        "tenant_id": scan.tenant_id,
        "catalog_id": scan.catalog_id,
        "intended_use": scan.intended_use,
        "match_status": scan.match_status,
        "policy_action": scan.policy_action,
        "rights_path": scan.rights_path,
        "reason_codes": list(scan.reason_codes or []),
        "coverage_status": scope.get("coverage_status"),
        "coverage_complete": bool(scope.get("complete_for_declared_catalog", False)),
        "anchor_status": scan.anchor_status,
        "proof_provider": proof.get("provider"),
        "packet_hash_sha256": proof.get("packet_hash_sha256"),
        "statement_id": (statement or {}).get("statement_id"),
        "statement_digest_sha256": (statement or {}).get("payload_digest_sha256"),
        "review_case_id": review_case_id,
        "completed_at": scan.completed_at.isoformat() if scan.completed_at else None,
        "notice": (
            "Source-scoped evidence and a policy recommendation. Not a legal "
            "infringement determination."
        ),
    }
    queued = queue_event(
        db, tenant_id=scan.tenant_id, event_type=EVENT_SCAN_COMPLETED, payload=payload
    )
    if review_case_id:
        queue_event(
            db,
            tenant_id=scan.tenant_id,
            event_type=EVENT_REVIEW_CASE_OPENED,
            payload={
                "schema": "creatorproof.webhook.review_case_opened.v1",
                "review_case_id": review_case_id,
                "scan_id": scan.id,
                "policy_action": scan.policy_action,
                "match_status": scan.match_status,
            },
        )
    return queued


class WebhookDispatcher:
    def __init__(self, *, session_factory, settings) -> None:
        self._session_factory = session_factory
        self._settings = settings

    def dispatch_once(self, limit: int = 20) -> int:
        from app.models import WebhookDelivery, WebhookEndpoint

        db = self._session_factory()
        delivered = 0
        try:
            now = datetime.now(UTC)
            rows = db.scalars(
                select(WebhookDelivery)
                .where(
                    WebhookDelivery.state.in_(
                        [WebhookDeliveryState.PENDING, WebhookDeliveryState.RETRYING]
                    ),
                    WebhookDelivery.next_attempt_at <= now,
                )
                .order_by(WebhookDelivery.created_at)
                .limit(limit)
            ).all()
            for row in rows:
                endpoint = db.get(WebhookEndpoint, row.endpoint_id)
                if endpoint is None or not endpoint.active:
                    row.state = str(WebhookDeliveryState.DEAD_LETTERED)
                    row.last_error = "ENDPOINT_INACTIVE"
                    continue
                delivered += 1 if self._attempt(db, row, endpoint) else 0
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("webhook_dispatch_failed")
        finally:
            db.close()
        return delivered

    def _attempt(self, db: Session, row, endpoint) -> bool:
        body = json.dumps(
            {
                "delivery_id": row.id,
                "event_type": row.event_type,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "data": row.payload,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        timestamp = str(int(datetime.now(UTC).timestamp()))
        row.attempts += 1
        try:
            if not self._settings.webhook_allow_private_hosts and _is_private_host(endpoint.url):
                raise ValueError("WEBHOOK_PRIVATE_HOST_BLOCKED")
            request = urllib.request.Request(  # noqa: S310 - scheme validated below
                endpoint.url,
                data=body,
                method="POST",
                headers={
                    "Content-Type": "application/json",
                    SIGNATURE_HEADER: sign_payload(endpoint.secret, timestamp, body),
                    TIMESTAMP_HEADER: timestamp,
                    DELIVERY_HEADER: row.id,
                    EVENT_HEADER: row.event_type,
                    CORRELATION_HEADER: row.correlation_id or "",
                },
            )
            if urllib.parse.urlparse(endpoint.url).scheme not in {"http", "https"}:
                raise ValueError("WEBHOOK_UNSUPPORTED_SCHEME")
            with urllib.request.urlopen(  # noqa: S310 - scheme validated above
                request, timeout=self._settings.webhook_timeout_seconds
            ) as response:
                row.response_status = int(response.status)
            row.state = str(WebhookDeliveryState.DELIVERED)
            row.delivered_at = datetime.now(UTC)
            row.last_error = None
            METRICS.increment("creatorproof_webhook_delivered_total", event_type=row.event_type)
            return True
        except Exception as exc:
            row.last_error = type(exc).__name__
            if isinstance(exc, urllib.error.HTTPError):
                row.response_status = int(exc.code)
            if row.attempts >= row.max_attempts:
                row.state = str(WebhookDeliveryState.DEAD_LETTERED)
                METRICS.increment(
                    "creatorproof_webhook_dead_lettered_total", event_type=row.event_type
                )
                log_event(
                    logger,
                    "webhook_dead_lettered",
                    delivery_id=row.id,
                    event_type=row.event_type,
                    attempts=row.attempts,
                )
            else:
                row.state = str(WebhookDeliveryState.RETRYING)
                row.next_attempt_at = datetime.now(UTC) + timedelta(
                    seconds=min(600, 2**row.attempts)
                )
            return False


class WebhookDispatcherThread(threading.Thread):
    def __init__(self, dispatcher: WebhookDispatcher, interval_seconds: float = 2.0) -> None:
        super().__init__(name="creatorproof-webhooks", daemon=True)
        self._dispatcher = dispatcher
        self._interval = interval_seconds
        self._stop_event = threading.Event()

    def run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._dispatcher.dispatch_once()
            except Exception:  # pragma: no cover - defensive
                logger.exception("webhook_thread_iteration_failed")
            self._stop_event.wait(self._interval)

    def stop(self) -> None:
        self._stop_event.set()
