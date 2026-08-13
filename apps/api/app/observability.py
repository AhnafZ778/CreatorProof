"""Structured logging, correlation identity and in-process metrics.

Logs never contain raw customer media, candidate bytes, detector payloads or
API secrets. Only stable identifiers, states and durations are emitted, so a
failed scan can be traced end to end from one correlation ID without exposing
tenant content.
"""

from __future__ import annotations

import json
import logging
import math
import os
import threading
import time
from collections import defaultdict
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

_correlation_id: ContextVar[str] = ContextVar("creatorproof_correlation_id", default="")
_tenant_id: ContextVar[str] = ContextVar("creatorproof_tenant_id", default="")

_REDACTED_KEYS = frozenset(
    {
        "api_key",
        "x-api-key",
        "authorization",
        "secret",
        "private_key",
        "eas_private_key",
        "password",
        "token",
    }
)


def new_correlation_id() -> str:
    return uuid4().hex


def current_correlation_id() -> str:
    value = _correlation_id.get()
    if not value:
        value = new_correlation_id()
        _correlation_id.set(value)
    return value


def set_correlation_id(value: str | None) -> str:
    resolved = (value or "").strip() or new_correlation_id()
    _correlation_id.set(resolved)
    return resolved


def set_tenant_context(tenant_id: str | None) -> None:
    _tenant_id.set(tenant_id or "")


def current_tenant_context() -> str:
    return _tenant_id.get()


@contextmanager
def correlation_scope(value: str | None = None):
    token = _correlation_id.set((value or "").strip() or new_correlation_id())
    try:
        yield _correlation_id.get()
    finally:
        _correlation_id.reset(token)


def _redact(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: ("[redacted]" if key.lower() in _REDACTED_KEYS else value)
        for key, value in payload.items()
    }


class JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        correlation = _correlation_id.get()
        if correlation:
            payload["correlation_id"] = correlation
        tenant = _tenant_id.get()
        if tenant:
            payload["tenant_id"] = tenant
        extra = getattr(record, "creatorproof", None)
        if isinstance(extra, dict):
            payload.update(_redact(extra))
        if record.exc_info:
            payload["error_class"] = getattr(record.exc_info[0], "__name__", "Exception")
        return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def configure_logging(log_format: str = "json", level: int = logging.INFO) -> None:
    handler = logging.StreamHandler()
    if log_format == "json":
        handler.setFormatter(JsonLogFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"),
        )
    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(level)


def log_event(logger: logging.Logger, message: str, /, level: int = logging.INFO, **fields) -> None:
    logger.log(level, message, extra={"creatorproof": fields})


_LATENCY_BUCKETS_MS = (5, 25, 50, 100, 250, 500, 1_000, 2_500, 5_000, 15_000, 60_000, 300_000)


class MetricsRegistry:
    """Minimal Prometheus-compatible registry.

    A dedicated OpenTelemetry collector is the production target; this registry
    keeps the same metric names available without adding a hard dependency, so a
    demo machine and CI both expose the operational surface.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[tuple[str, tuple[tuple[str, str], ...]], float] = defaultdict(float)
        self._gauges: dict[tuple[str, tuple[tuple[str, str], ...]], float] = {}
        self._histograms: dict[tuple[str, tuple[tuple[str, str], ...]], list[float]] = defaultdict(
            list
        )
        self.started_at = time.time()

    @staticmethod
    def _key(labels: dict[str, str] | None) -> tuple[tuple[str, str], ...]:
        return tuple(sorted((str(k), str(v)) for k, v in (labels or {}).items()))

    def increment(self, name: str, value: float = 1.0, **labels: str) -> None:
        with self._lock:
            self._counters[(name, self._key(labels))] += value

    def set_gauge(self, name: str, value: float, **labels: str) -> None:
        with self._lock:
            self._gauges[(name, self._key(labels))] = value

    def observe(self, name: str, value_ms: float, **labels: str) -> None:
        with self._lock:
            samples = self._histograms[(name, self._key(labels))]
            samples.append(value_ms)
            if len(samples) > 5_000:
                del samples[: len(samples) - 5_000]

    @contextmanager
    def time_block(self, name: str, **labels: str):
        started = time.perf_counter()
        try:
            yield
        finally:
            self.observe(name, (time.perf_counter() - started) * 1000.0, **labels)

    def quantile(self, name: str, quantile: float, **labels: str) -> float | None:
        with self._lock:
            samples = sorted(self._histograms.get((name, self._key(labels)), []))
        if not samples:
            return None
        index = min(len(samples) - 1, max(0, math.ceil(quantile * len(samples)) - 1))
        return samples[index]

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            counters = {
                self._render(name, labels): value
                for (name, labels), value in self._counters.items()
            }
            gauges = {
                self._render(name, labels): value for (name, labels), value in self._gauges.items()
            }
            histograms = {
                self._render(name, labels): {
                    "count": len(values),
                    "p50_ms": _percentile(values, 0.50),
                    "p95_ms": _percentile(values, 0.95),
                    "p99_ms": _percentile(values, 0.99),
                }
                for (name, labels), values in self._histograms.items()
                if values
            }
        return {
            "uptime_seconds": round(time.time() - self.started_at, 3),
            "process_id": os.getpid(),
            "counters": counters,
            "gauges": gauges,
            "histograms": histograms,
        }

    def render_prometheus(self) -> str:
        snapshot = self.snapshot()
        lines: list[str] = []
        for key, value in sorted(snapshot["counters"].items()):
            lines.append(f"{key} {value}")
        for key, value in sorted(snapshot["gauges"].items()):
            lines.append(f"{key} {value}")
        for key, stats in sorted(snapshot["histograms"].items()):
            base = key[:-1] if key.endswith("}") else key
            separator = "," if key.endswith("}") else "{"
            suffix = "}" if key.endswith("}") else "}"
            quantiles = (("0.5", "p50_ms"), ("0.95", "p95_ms"), ("0.99", "p99_ms"))
            for quantile_label, field in quantiles:
                if stats[field] is None:
                    continue
                lines.append(f'{base}{separator}quantile="{quantile_label}"{suffix} {stats[field]}')
            lines.append(f"{base.split('{')[0]}_count {stats['count']}")
        return "\n".join(lines) + "\n"

    @staticmethod
    def _render(name: str, labels: tuple[tuple[str, str], ...]) -> str:
        if not labels:
            return name
        rendered = ",".join(f'{key}="{value}"' for key, value in labels)
        return f"{name}{{{rendered}}}"


def _percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(quantile * len(ordered)) - 1))
    return round(ordered[index], 3)


METRICS = MetricsRegistry()
