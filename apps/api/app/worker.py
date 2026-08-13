"""Scan worker.

The worker acknowledges a message only after the runner has driven the scan to a
durable state. A crash before acknowledgement leaves the entry pending, and
``XAUTOCLAIM`` hands it to a healthy consumer. A message that keeps failing is
dead-lettered rather than retried forever, and the scan itself remains inspectable
in the database.
"""

from __future__ import annotations

import argparse
import logging
import signal
import time

from app.container import build_container, initialize_database
from app.core.config import Settings
from app.domain.platform import WorkerClass
from app.observability import METRICS, configure_logging, correlation_scope, log_event
from app.services.evidence import process_scan
from app.services.jobs import RedisJobQueue, RedisStreamsJobQueue
from app.services.orchestration import OutboxDispatcher, StageLedger, worker_identity
from app.services.scan_runner import recover_orphaned_scans
from app.services.webhooks import WebhookDispatcher

logger = logging.getLogger("creatorproof.worker")

MAX_STREAM_DELIVERIES = 5

_shutdown = False


def _request_shutdown(signum, frame) -> None:  # noqa: ARG001
    global _shutdown
    _shutdown = True
    logger.info("worker_shutdown_requested")


def _handle(container, scan_id: str, correlation_id: str | None) -> None:
    with correlation_scope(correlation_id):
        started = time.perf_counter()
        process_scan(container, scan_id)
        METRICS.observe(
            "creatorproof_worker_scan_duration_ms", (time.perf_counter() - started) * 1000.0
        )


def _run_streams(container, settings: Settings, consumer: str) -> None:
    queue = container.queue
    if not isinstance(queue, RedisStreamsJobQueue):
        raise RuntimeError("Streams worker requires CREATORPROOF_REDIS_TRANSPORT=streams")
    outbox = OutboxDispatcher(
        session_factory=container.database.system_session,
        queue=queue,
        max_attempts=settings.outbox_max_attempts,
    )
    ledger: StageLedger = container.stage_ledger
    webhooks = WebhookDispatcher(
        session_factory=container.database.system_session, settings=settings
    )
    log_event(logger, "worker_ready", transport=queue.name, stream=queue.stream_name)

    last_maintenance = 0.0
    while not _shutdown:
        now = time.monotonic()
        if now - last_maintenance > settings.stage_reaper_interval_seconds:
            last_maintenance = now
            outbox.dispatch_once()
            webhooks.dispatch_once()
            if container.blockchain is not None:
                container.blockchain.dispatch_once()
            db = container.database.system_session()
            try:
                ledger.reap_expired(db)
            finally:
                db.close()

        messages = queue.claim_stale(
            consumer=consumer, min_idle_ms=settings.stage_lease_seconds * 1000
        )
        messages += queue.read(consumer=consumer, count=1, block_ms=2_000)
        for message_id, payload in messages:
            scan_id = str(payload.get("scan_id") or "")
            if not scan_id:
                queue.dead_letter(message_id, payload, "MISSING_SCAN_ID")
                continue
            if queue.delivery_count(message_id) > MAX_STREAM_DELIVERIES:
                queue.dead_letter(message_id, payload, "MAX_DELIVERIES_EXCEEDED")
                log_event(logger, "scan_message_dead_lettered", scan_id=scan_id)
                continue
            try:
                _handle(container, scan_id, payload.get("correlation_id"))
            except Exception:
                # Leave the entry pending so it is redelivered. The scan row already
                # records whether the failure was transient or terminal.
                logger.exception("scan_failed scan_id=%s", scan_id)
                continue
            queue.acknowledge(message_id)


def _run_list(container, settings: Settings) -> None:
    """Run the compatibility list transport with leases, retry and dead letters."""
    queue = container.queue
    if not isinstance(queue, RedisJobQueue):
        raise RuntimeError("List worker requires CREATORPROOF_REDIS_TRANSPORT=list")
    log_event(logger, "worker_ready", transport="redis-list", queue=settings.redis_queue_name)
    last_recovery = 0.0
    while not _shutdown:
        now = time.monotonic()
        if now - last_recovery >= settings.redis_job_recovery_interval_seconds:
            last_recovery = now
            queue.recover_stale()
            if container.blockchain is not None:
                container.blockchain.dispatch_once()
        job = queue.claim(timeout=settings.redis_job_claim_timeout_seconds)
        if job is None:
            continue
        try:
            _handle(container, job.scan_id, None)
        except Exception as exc:
            outcome = queue.fail(job, type(exc).__name__)
            logger.exception("scan_failed scan_id=%s queue_outcome=%s", job.scan_id, outcome)
        else:
            queue.acknowledge(job)


def main() -> None:
    parser = argparse.ArgumentParser(description="CreatorProof scan worker")
    parser.add_argument(
        "--worker-class",
        choices=[item.value for item in WorkerClass],
        default=WorkerClass.CPU.value,
        help="Advertised role for this worker process.",
    )
    args = parser.parse_args()

    settings = Settings()
    configure_logging(settings.log_format)
    if settings.job_backend != "redis":
        raise RuntimeError("Worker requires CREATORPROOF_JOB_BACKEND=redis")

    signal.signal(signal.SIGTERM, _request_shutdown)
    signal.signal(signal.SIGINT, _request_shutdown)

    container = build_container(settings)
    initialize_database(container)
    recover_orphaned_scans(container)
    consumer = f"{args.worker_class}:{worker_identity()}"

    try:
        if settings.redis_transport == "streams":
            _run_streams(container, settings, consumer)
        else:
            _run_list(container, settings)
    finally:
        if container.queue is not None:
            container.queue.close()
        log_event(logger, "worker_stopped")


if __name__ == "__main__":
    main()
