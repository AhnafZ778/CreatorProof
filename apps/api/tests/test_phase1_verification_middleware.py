"""Unauthenticated verification admission and credential-redaction behavior."""

import logging
from contextlib import contextmanager

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import Settings
from app.middleware import CorrelationMiddleware, RateLimitMiddleware, TokenBucketLimiter
from app.observability import METRICS


def _app():
    app = FastAPI()
    app.add_middleware(
        RateLimitMiddleware, limiter=TokenBucketLimiter(requests_per_minute=1, burst=1)
    )
    app.add_middleware(CorrelationMiddleware)

    @app.get("/verify/{token}")
    def verifier(token: str):
        raise HTTPException(status_code=404, detail="Verification token not found or expired")

    return app


@contextmanager
def _capture_http_logs(caplog):
    # App initialization can replace root handlers and third-party logging
    # configuration can disable an existing named logger. This test exercises
    # emitted HTTP records under an explicitly enabled, isolated capture path.
    logger = logging.getLogger("creatorproof.http")
    inherited_disabled, inherited_propagation = logger.disabled, logger.propagate
    capture_already_attached = caplog.handler in logger.handlers
    logger.disabled = False
    logger.propagate = False
    if not capture_already_attached:
        logger.addHandler(caplog.handler)
    try:
        with caplog.at_level(logging.INFO, logger=logger.name):
            yield
    finally:
        if not capture_already_attached:
            logger.removeHandler(caplog.handler)
        logger.disabled = inherited_disabled
        logger.propagate = inherited_propagation


@pytest.mark.parametrize(
    "inherited_logging_state", ["default", "disabled", "propagation_off", "root_capture_removed"]
)
def test_public_rate_limit_uses_ip_and_ignores_rotating_untrusted_headers(
    caplog, monkeypatch, inherited_logging_state
):
    logger = logging.getLogger("creatorproof.http")
    if inherited_logging_state == "disabled":
        monkeypatch.setattr(logger, "disabled", True)
    elif inherited_logging_state == "propagation_off":
        monkeypatch.setattr(logger, "propagate", False)
    elif inherited_logging_state == "root_capture_removed":
        monkeypatch.setattr(logging.getLogger(), "handlers", [])
    inherited_flags = logger.disabled, logger.propagate
    inherited_handlers = logger.handlers.copy()
    token = "credential-never-exposed-in-public-metric-labels"
    with _capture_http_logs(caplog), TestClient(_app()) as client:
        first = client.get(f"/verify/{token}", headers={"X-API-Key": "random-key-one"})
        second = client.get(f"/verify/{token}", headers={"X-API-Key": "random-key-two"})
    assert (logger.disabled, logger.propagate) == inherited_flags
    assert logger.handlers == inherited_handlers
    assert first.status_code == 404
    assert second.status_code == 429
    assert int(second.headers["retry-after"]) >= 1
    for response in [first, second]:
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["referrer-policy"] == "no-referrer"
    http_records = [record for record in caplog.records if record.name == "creatorproof.http"]
    assert len(http_records) == 2
    assert all(record.getMessage() == "http_request" for record in http_records)
    assert {record.creatorproof["status_code"] for record in http_records} == {404, 429}
    assert all(record.creatorproof["path"] == "/verify/{public_token}" for record in http_records)
    assert all(token not in repr(record.__dict__) for record in http_records)
    metrics = METRICS.render_prometheus()
    assert token not in metrics
    assert "/verify/{public_token}" in metrics


def test_different_public_clients_receive_independent_admission_budget():
    app = _app()
    with TestClient(app, client=("192.0.2.1", 1234)) as first_client:
        assert first_client.get("/verify/a").status_code == 404
        assert first_client.get("/verify/b").status_code == 429
    with TestClient(app, client=("192.0.2.2", 1234)) as second_client:
        assert second_client.get("/verify/c").status_code == 404


@pytest.mark.parametrize(
    "origin",
    [
        "https://verify.example.org/a/path",
        "https://user:password@verify.example.org",
        "https://verify.example.org?key=secret",
        "https://verify.example.org#fragment",
        "http://verify.example.org",
        "//verify.example.org",
        "https://verify.example.org:bad-port",
    ],
)
def test_public_verification_origin_rejects_unsafe_or_ambiguous_urls(origin):
    with pytest.raises(ValidationError):
        Settings(environment="test", _env_file=None, public_verification_base_url=origin)


@pytest.mark.parametrize("origin", ["https://verify.example.org/", "http://localhost:8000"])
def test_public_verification_origin_accepts_explicit_secure_or_local_origin(origin):
    settings = Settings(environment="test", _env_file=None, public_verification_base_url=origin)
    assert settings.public_verification_base_url == origin.rstrip("/")
