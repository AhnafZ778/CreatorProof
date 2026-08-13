"""Scan work transports.

All backends satisfy the same contract: ``publish`` hands a stable identifier to
a transport, and the database remains the authority for what has actually run.
Redis Streams adds acknowledgement, pending-entry inspection, bounded redelivery
and a dead-letter stream; the local backends keep zero-infrastructure development
working without changing the durable state model.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from threading import Lock
from typing import Protocol
from uuid import uuid4

from redis import Redis

logger = logging.getLogger("creatorproof.jobs")


class JobQueue(Protocol):
    name: str

    def enqueue(self, scan_id: str) -> None: ...

    def publish(self, topic: str, payload: dict) -> None: ...

    def healthy(self) -> bool: ...

    def stats(self) -> dict: ...

    def close(self) -> None: ...


class _DirectPublishMixin:
    """Local transports execute the payload instead of moving it over a network."""

    def publish(self, topic: str, payload: dict) -> None:
        scan_id = str(payload.get("scan_id") or "")
        if not scan_id:
            logger.warning("outbox_payload_without_scan_id topic=%s", topic)
            return
        self.enqueue(scan_id)


class InlineJobQueue(_DirectPublishMixin):
    name = "inline"

    def __init__(self, callback) -> None:
        self.callback = callback

    def enqueue(self, scan_id: str) -> None:
        self.callback(scan_id)

    def healthy(self) -> bool:
        return True

    def stats(self) -> dict:
        return {"transport": self.name, "depth": 0, "pending": 0}

    def close(self) -> None:
        return None


class LocalThreadJobQueue(_DirectPublishMixin):
    """Non-blocking, single-process queue for local demos.

    The executor deliberately defaults to one worker. CreatorProof model providers
    are resident process resources; running several scans against the same CPU/GPU
    at once creates contention and can make every scan slower. Redis remains the
    durable deployment option because these local jobs do not survive an API restart.
    """

    name = "local-thread"

    def __init__(self, callback, *, max_workers: int = 1) -> None:
        self.callback = callback
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="creatorproof-scan",
        )
        self._closed = False
        self._lock = Lock()
        self._inflight = 0

    @staticmethod
    def _report_failure(future: Future) -> None:
        try:
            future.result()
        except Exception:
            logger.exception("background scan failed")

    def _run(self, scan_id: str) -> None:
        try:
            self.callback(scan_id)
        finally:
            with self._lock:
                self._inflight = max(0, self._inflight - 1)

    def enqueue(self, scan_id: str) -> None:
        with self._lock:
            if self._closed:
                raise RuntimeError("LOCAL_JOB_QUEUE_CLOSED")
            self._inflight += 1
            future = self._executor.submit(self._run, scan_id)
        future.add_done_callback(self._report_failure)

    def healthy(self) -> bool:
        with self._lock:
            return not self._closed

    def stats(self) -> dict:
        with self._lock:
            return {"transport": self.name, "depth": self._inflight, "pending": self._inflight}

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        self._executor.shutdown(wait=True, cancel_futures=False)


@dataclass(frozen=True, slots=True)
class RedisScanJob:
    scan_id: str
    attempt: int
    job_id: str
    raw_payload: str


class RedisJobQueue:
    """Redis list queue with atomic claim, acknowledgment, retry, and stale recovery."""

    name = "redis"

    _ACK_SCRIPT = """
local removed = redis.call('LREM', KEYS[1], 1, ARGV[1])
redis.call('ZREM', KEYS[2], ARGV[1])
return removed
"""
    _TRANSITION_SCRIPT = """
local removed = redis.call('LREM', KEYS[1], 1, ARGV[1])
redis.call('ZREM', KEYS[2], ARGV[1])
if removed == 1 then
  redis.call('LPUSH', KEYS[3], ARGV[2])
end
return removed
"""

    def __init__(
        self,
        url: str,
        queue_name: str,
        *,
        max_attempts: int = 3,
        lease_seconds: int = 1800,
        client=None,
    ) -> None:
        self.client = client or Redis.from_url(url, decode_responses=True)
        self.queue_name = queue_name
        self.processing_name = f"{queue_name}:processing"
        self.lease_name = f"{queue_name}:leases"
        self.dead_name = f"{queue_name}:dead"
        self.max_attempts = max(1, int(max_attempts))
        self.lease_seconds = max(1, int(lease_seconds))

    @staticmethod
    def _encode(
        scan_id: str,
        *,
        attempt: int,
        job_id: str,
        reason: str | None = None,
        recovered: bool = False,
    ) -> str:
        payload = {
            "schema": "creatorproof.redis_scan_job.v1",
            "scan_id": scan_id,
            "attempt": int(attempt),
            "job_id": job_id,
            "enqueued_at_unix": round(time.time(), 6),
            "recovered_from_expired_lease": recovered,
        }
        if reason:
            payload["last_error_code"] = reason[:160]
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _decode(raw: str) -> RedisScanJob:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            # Compatibility with the original queue, which stored only the scan ID.
            return RedisScanJob(scan_id=raw, attempt=0, job_id=f"legacy:{raw}", raw_payload=raw)
        if (
            not isinstance(payload, dict)
            or payload.get("schema") != "creatorproof.redis_scan_job.v1"
        ):
            raise ValueError("REDIS_SCAN_JOB_SCHEMA_INVALID")
        scan_id = str(payload.get("scan_id") or "").strip()
        job_id = str(payload.get("job_id") or "").strip()
        attempt = int(payload.get("attempt") or 0)
        if not scan_id or not job_id or attempt < 0:
            raise ValueError("REDIS_SCAN_JOB_PAYLOAD_INVALID")
        return RedisScanJob(scan_id=scan_id, attempt=attempt, job_id=job_id, raw_payload=raw)

    def enqueue(self, scan_id: str) -> None:
        payload = self._encode(scan_id, attempt=0, job_id=uuid4().hex)
        self.client.lpush(self.queue_name, payload)

    def publish(self, topic: str, payload: dict) -> None:
        del topic
        scan_id = str(payload.get("scan_id") or "")
        if scan_id:
            self.enqueue(scan_id)

    def claim(self, *, timeout: int = 5) -> RedisScanJob | None:
        raw = self.client.brpoplpush(
            self.queue_name,
            self.processing_name,
            timeout=max(1, int(timeout)),
        )
        if raw is None:
            return None
        try:
            job = self._decode(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            self.client.eval(
                self._TRANSITION_SCRIPT,
                3,
                self.processing_name,
                self.lease_name,
                self.dead_name,
                raw,
                raw,
            )
            return None
        self.client.zadd(self.lease_name, {raw: time.time() + self.lease_seconds})
        return job

    def renew(self, job: RedisScanJob) -> None:
        self.client.zadd(
            self.lease_name,
            {job.raw_payload: time.time() + self.lease_seconds},
            xx=True,
        )

    def acknowledge(self, job: RedisScanJob) -> bool:
        return bool(
            self.client.eval(
                self._ACK_SCRIPT,
                2,
                self.processing_name,
                self.lease_name,
                job.raw_payload,
            )
        )

    def fail(self, job: RedisScanJob, reason: str) -> str:
        next_attempt = job.attempt + 1
        exhausted = next_attempt >= self.max_attempts
        destination = self.dead_name if exhausted else self.queue_name
        replacement = self._encode(
            job.scan_id,
            attempt=next_attempt,
            job_id=job.job_id,
            reason=reason,
        )
        moved = self.client.eval(
            self._TRANSITION_SCRIPT,
            3,
            self.processing_name,
            self.lease_name,
            destination,
            job.raw_payload,
            replacement,
        )
        return "DEAD_LETTERED" if exhausted and moved else "REQUEUED" if moved else "NOT_CLAIMED"

    def recover_stale(self, *, now: float | None = None, limit: int = 100) -> dict:
        timestamp = time.time() if now is None else float(now)
        expired = self.client.zrangebyscore(
            self.lease_name,
            "-inf",
            timestamp,
            start=0,
            num=max(1, int(limit)),
        )
        recovered = 0
        dead_lettered = 0
        malformed = 0
        for raw in expired:
            try:
                job = self._decode(raw)
                next_attempt = job.attempt + 1
                exhausted = next_attempt >= self.max_attempts
                destination = self.dead_name if exhausted else self.queue_name
                replacement = self._encode(
                    job.scan_id,
                    attempt=next_attempt,
                    job_id=job.job_id,
                    reason="LEASE_EXPIRED",
                    recovered=True,
                )
            except (TypeError, ValueError, json.JSONDecodeError):
                malformed += 1
                destination = self.dead_name
                replacement = raw
                exhausted = True
            moved = self.client.eval(
                self._TRANSITION_SCRIPT,
                3,
                self.processing_name,
                self.lease_name,
                destination,
                raw,
                replacement,
            )
            if moved:
                if exhausted:
                    dead_lettered += 1
                else:
                    recovered += 1
        return {
            "expired": len(expired),
            "recovered": recovered,
            "dead_lettered": dead_lettered,
            "malformed": malformed,
        }

    def healthy(self) -> bool:
        return bool(self.client.ping())

    def stats(self) -> dict:
        try:
            waiting = int(self.client.llen(self.queue_name))
            processing = int(self.client.llen(self.processing_name))
            dead = int(self.client.llen(self.dead_name))
        except Exception:
            return {"transport": self.name, "depth": -1, "pending": -1, "dead_letter": -1}
        return {
            "transport": self.name,
            "depth": waiting,
            "pending": processing,
            "dead_letter": dead,
        }

    def close(self) -> None:
        self.client.close()


class RedisStreamsJobQueue:
    """Durable transport using Redis Streams consumer groups.

    Redis owns no irreplaceable state: a message carries only identifiers, and the
    database decides whether the referenced work still needs to run. Duplicate
    delivery is therefore expected and safe.
    """

    name = "redis-streams"
    DEAD_LETTER_SUFFIX = ":dead"

    def __init__(
        self,
        url: str,
        *,
        stream_name: str,
        consumer_group: str,
        maxlen: int = 10_000,
    ) -> None:
        self.client = Redis.from_url(url, decode_responses=True)
        self.stream_name = stream_name
        self.consumer_group = consumer_group
        self.dead_letter_stream = f"{stream_name}{self.DEAD_LETTER_SUFFIX}"
        self.maxlen = maxlen
        self.ensure_group()

    def ensure_group(self) -> None:
        try:
            self.client.xgroup_create(
                name=self.stream_name, groupname=self.consumer_group, id="0", mkstream=True
            )
        except Exception as exc:
            if "BUSYGROUP" not in str(exc):
                logger.warning("redis_stream_group_create_failed error=%s", type(exc).__name__)

    def enqueue(self, scan_id: str) -> None:
        self.publish("scan.accepted", {"scan_id": scan_id})

    def publish(self, topic: str, payload: dict) -> None:
        self.client.xadd(
            self.stream_name,
            {"topic": topic, "payload": json.dumps(payload, separators=(",", ":"))},
            maxlen=self.maxlen,
            approximate=True,
        )

    def read(
        self, *, consumer: str, count: int = 1, block_ms: int = 5_000
    ) -> list[tuple[str, dict]]:
        entries = self.client.xreadgroup(
            groupname=self.consumer_group,
            consumername=consumer,
            streams={self.stream_name: ">"},
            count=count,
            block=block_ms,
        )
        return _flatten_stream_entries(entries)

    def claim_stale(
        self, *, consumer: str, min_idle_ms: int = 60_000, count: int = 10
    ) -> list[tuple[str, dict]]:
        """Reclaim messages whose original consumer died before acknowledging."""
        try:
            _, messages, _ = self.client.xautoclaim(
                name=self.stream_name,
                groupname=self.consumer_group,
                consumername=consumer,
                min_idle_time=min_idle_ms,
                count=count,
            )
        except Exception as exc:
            logger.warning("redis_stream_autoclaim_failed error=%s", type(exc).__name__)
            return []
        return _decode_messages(messages)

    def acknowledge(self, message_id: str) -> None:
        self.client.xack(self.stream_name, self.consumer_group, message_id)

    def dead_letter(self, message_id: str, payload: dict, reason: str) -> None:
        self.client.xadd(
            self.dead_letter_stream,
            {
                "original_id": message_id,
                "reason": reason,
                "payload": json.dumps(payload, separators=(",", ":")),
            },
            maxlen=self.maxlen,
            approximate=True,
        )
        self.acknowledge(message_id)

    def delivery_count(self, message_id: str) -> int:
        try:
            pending = self.client.xpending_range(
                self.stream_name, self.consumer_group, min=message_id, max=message_id, count=1
            )
        except Exception:
            return 1
        if not pending:
            return 1
        return int(pending[0].get("times_delivered", 1))

    def healthy(self) -> bool:
        return bool(self.client.ping())

    def stats(self) -> dict:
        try:
            depth = int(self.client.xlen(self.stream_name))
            summary = self.client.xpending(self.stream_name, self.consumer_group)
            pending = int(summary.get("pending", 0)) if isinstance(summary, dict) else 0
            dead = int(self.client.xlen(self.dead_letter_stream))
        except Exception:
            return {"transport": self.name, "depth": -1, "pending": -1, "dead_letter": -1}
        return {
            "transport": self.name,
            "stream": self.stream_name,
            "group": self.consumer_group,
            "depth": depth,
            "pending": pending,
            "dead_letter": dead,
        }

    def close(self) -> None:
        self.client.close()


def _flatten_stream_entries(entries) -> list[tuple[str, dict]]:
    if not entries:
        return []
    flattened: list[tuple[str, dict]] = []
    for _stream, messages in entries:
        flattened.extend(_decode_messages(messages))
    return flattened


def _decode_messages(messages) -> list[tuple[str, dict]]:
    decoded: list[tuple[str, dict]] = []
    for message_id, fields in messages or []:
        raw = fields.get("payload") if isinstance(fields, dict) else None
        try:
            payload = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            payload = {}
        payload.setdefault("topic", (fields or {}).get("topic"))
        decoded.append((message_id, payload))
    return decoded


def iter_messages(queue: RedisStreamsJobQueue, *, consumer: str) -> Iterator[tuple[str, dict]]:
    """Yield new messages, periodically reclaiming abandoned ones."""
    while True:
        reclaimed = queue.claim_stale(consumer=consumer)
        yield from reclaimed
        yield from queue.read(consumer=consumer)
