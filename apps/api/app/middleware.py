"""Request middleware: correlation identity, metrics and admission control.

Rate limiting here is a per-process token bucket. It protects a single API
instance and a demo machine; a multi-instance deployment puts a shared limiter in
front of the service, which the operations guide records explicitly rather than
implying this is a distributed quota.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from threading import Lock

from fastapi import Request, Response, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.observability import METRICS, current_correlation_id, log_event, set_correlation_id

logger = logging.getLogger("creatorproof.http")

CORRELATION_HEADER = "X-Correlation-Id"
_EXEMPT_PATHS = frozenset({"/healthz", "/readyz", "/metrics", "/openapi.json", "/docs"})


class TokenBucketLimiter:
    def __init__(self, *, requests_per_minute: int, burst: int) -> None:
        self._rate_per_second = requests_per_minute / 60.0
        self._burst = float(burst)
        self._lock = Lock()
        self._buckets: dict[str, tuple[float, float]] = defaultdict(
            lambda: (self._burst, time.monotonic())
        )

    def allow(self, key: str, *, cost: float = 1.0) -> tuple[bool, float]:
        if cost <= 0:
            raise ValueError("rate-limit cost must be positive")
        with self._lock:
            tokens, updated = self._buckets[key]
            now = time.monotonic()
            tokens = min(self._burst, tokens + (now - updated) * self._rate_per_second)
            if tokens < cost:
                self._buckets[key] = (tokens, now)
                retry_after = (cost - tokens) / self._rate_per_second
                return False, max(1.0, retry_after)
            self._buckets[key] = (tokens - cost, now)
            return True, 0.0


class CorrelationMiddleware(BaseHTTPMiddleware):
    """Attach one correlation id to a request, its logs, its scan and its webhooks."""

    async def dispatch(self, request: Request, call_next):
        correlation_id = set_correlation_id(request.headers.get(CORRELATION_HEADER))
        request.state.correlation_id = correlation_id
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            duration_ms = (time.perf_counter() - started) * 1000.0
            METRICS.increment(
                "creatorproof_http_requests_total",
                method=request.method,
                path=request.url.path,
                status="500",
            )
            log_event(
                logger,
                "http_request_failed",
                level=logging.ERROR,
                method=request.method,
                path=request.url.path,
                duration_ms=round(duration_ms, 3),
            )
            raise
        duration_ms = (time.perf_counter() - started) * 1000.0
        response.headers[CORRELATION_HEADER] = correlation_id
        METRICS.increment(
            "creatorproof_http_requests_total",
            method=request.method,
            path=request.url.path,
            status=str(response.status_code),
        )
        METRICS.observe(
            "creatorproof_http_request_duration_ms",
            duration_ms,
            method=request.method,
            path=request.url.path,
        )
        log_event(
            logger,
            "http_request",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=round(duration_ms, 3),
        )
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, limiter: TokenBucketLimiter) -> None:
        super().__init__(app)
        self._limiter = limiter

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.url.path in _EXEMPT_PATHS:
            return await call_next(request)
        # Bucketing by credential prefix keeps one noisy tenant from consuming
        # another tenant's admission budget.
        api_key = request.headers.get("X-API-Key", "")
        key = api_key[:16] if api_key else (request.client.host if request.client else "anonymous")
        # Scan status is intentionally polled while CPU-bound evidence stages run.
        # Charge those authenticated, read-only requests at one tenth of a normal
        # request so progress polling remains bounded without exhausting the same
        # admission budget used by expensive writes.
        is_scan_status_poll = request.method == "GET" and request.url.path.startswith("/v1/scans/")
        allowed, retry_after = self._limiter.allow(key, cost=0.1 if is_scan_status_poll else 1.0)
        if not allowed:
            METRICS.increment("creatorproof_rate_limited_total", path=request.url.path)
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={
                    "detail": {
                        "code": "RATE_LIMITED",
                        "message": "Too many requests. Retry after the indicated delay.",
                    }
                },
                headers={
                    "Retry-After": str(int(retry_after)),
                    CORRELATION_HEADER: current_correlation_id(),
                },
            )
        return await call_next(request)
