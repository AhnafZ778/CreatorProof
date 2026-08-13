from __future__ import annotations

import math
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field


@dataclass(slots=True)
class RuntimeTelemetry:
    metadata: dict[str, object] = field(default_factory=dict)
    counters: dict[str, int] = field(default_factory=dict)
    timings: dict[str, dict[str, float | int]] = field(default_factory=dict)
    observations: dict[str, dict[str, float | int]] = field(default_factory=dict)

    def increment(self, name: str, amount: int = 1) -> None:
        self.counters[name] = self.counters.get(name, 0) + int(amount)

    def duration(self, name: str, milliseconds: float) -> None:
        value = float(milliseconds)
        if not math.isfinite(value) or value < 0:
            return
        row = self.timings.setdefault(name, {"count": 0, "total_ms": 0.0, "max_ms": 0.0})
        row["count"] = int(row["count"]) + 1
        row["total_ms"] = float(row["total_ms"]) + value
        row["max_ms"] = max(float(row["max_ms"]), value)

    def observe(self, name: str, value: float | int | None) -> None:
        if value is None:
            return
        number = float(value)
        if not math.isfinite(number):
            return
        row = self.observations.setdefault(
            name,
            {"count": 0, "sum": 0.0, "minimum": number, "maximum": number},
        )
        row["count"] = int(row["count"]) + 1
        row["sum"] = float(row["sum"]) + number
        row["minimum"] = min(float(row["minimum"]), number)
        row["maximum"] = max(float(row["maximum"]), number)

    def snapshot(self) -> dict:
        return {
            "schema": "creatorproof.runtime_telemetry.v1",
            "metadata": dict(sorted(self.metadata.items())),
            "counters": dict(sorted(self.counters.items())),
            "timings_ms": {
                name: {
                    "count": int(row["count"]),
                    "total": round(float(row["total_ms"]), 3),
                    "mean": round(float(row["total_ms"]) / max(int(row["count"]), 1), 3),
                    "maximum": round(float(row["max_ms"]), 3),
                }
                for name, row in sorted(self.timings.items())
            },
            "score_summaries": {
                name: {
                    "count": int(row["count"]),
                    "mean": round(float(row["sum"]) / max(int(row["count"]), 1), 6),
                    "minimum": round(float(row["minimum"]), 6),
                    "maximum": round(float(row["maximum"]), 6),
                }
                for name, row in sorted(self.observations.items())
            },
            "semantics": (
                "PER_SCAN_OPERATIONAL_DIAGNOSTICS_AND_SCORE_SUMMARIES_NOT_ACCURACY_METRICS"
            ),
        }


_CURRENT: ContextVar[RuntimeTelemetry | None] = ContextVar(
    "creatorproof_runtime_telemetry",
    default=None,
)


@contextmanager
def telemetry_scope(metadata: dict[str, object] | None = None) -> Iterator[RuntimeTelemetry]:
    telemetry = RuntimeTelemetry(metadata=dict(metadata or {}))
    token = _CURRENT.set(telemetry)
    try:
        yield telemetry
    finally:
        _CURRENT.reset(token)


def current_telemetry() -> RuntimeTelemetry | None:
    return _CURRENT.get()


def increment_counter(name: str, amount: int = 1) -> None:
    telemetry = current_telemetry()
    if telemetry is not None:
        telemetry.increment(name, amount)


def record_duration(name: str, milliseconds: float) -> None:
    telemetry = current_telemetry()
    if telemetry is not None:
        telemetry.duration(name, milliseconds)


def record_observation(name: str, value: float | int | None) -> None:
    telemetry = current_telemetry()
    if telemetry is not None:
        telemetry.observe(name, value)
