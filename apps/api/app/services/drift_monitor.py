from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

from app.services.model_bundle import canonical_json_digest

DRIFT_REGISTRY_SCHEMA = "creatorproof.drift_baseline_registry.v1"


@dataclass(frozen=True, slots=True)
class DriftBaselineRegistry:
    registry_id: str
    records: tuple[dict, ...]
    digest_sha256: str

    def status(self) -> dict:
        return {
            "registry_id": self.registry_id,
            "registry_digest_sha256": self.digest_sha256,
            "baseline_count": len(self.records),
            "state": "READY" if self.records else "NOT_CONFIGURED",
        }


def load_drift_baseline_registry(path: Path | str) -> DriftBaselineRegistry:
    source = Path(path)
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read drift baseline registry: {type(exc).__name__}") from exc
    if not isinstance(payload, dict) or payload.get("schema") != DRIFT_REGISTRY_SCHEMA:
        raise ValueError("unsupported drift baseline registry schema")
    registry_id = str(payload.get("registry_id") or "").strip()
    if not registry_id:
        raise ValueError("drift baseline registry_id is required")
    records = payload.get("records")
    if not isinstance(records, list):
        raise ValueError("drift baseline records must be an array")
    seen: set[tuple[str, str]] = set()
    validated: list[dict] = []
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise ValueError(f"drift baseline record[{index}] must be an object")
        required = (
            "lane",
            "score_name",
            "domain_id",
            "model_bundle_id",
            "model_bundle_manifest_digest_sha256",
            "source_report_digest_sha256",
        )
        missing = [key for key in required if not str(record.get(key) or "").strip()]
        if missing:
            raise ValueError(f"drift baseline record[{index}] missing: {','.join(missing)}")
        key = (str(record["lane"]), str(record["score_name"]))
        if key in seen:
            raise ValueError("drift baseline lane/score_name values must be unique")
        seen.add(key)
        for digest_field in (
            "model_bundle_manifest_digest_sha256",
            "source_report_digest_sha256",
        ):
            digest = str(record[digest_field]).lower()
            if len(digest) != 64 or any(
                character not in "0123456789abcdef" for character in digest
            ):
                raise ValueError(f"drift baseline {digest_field} must be SHA-256")
        for numeric in (
            "baseline_mean",
            "baseline_standard_deviation",
            "warning_standardized_shift",
            "revalidation_standardized_shift",
        ):
            value = float(record.get(numeric))
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"drift baseline {numeric} must be non-negative")
        minimum = int(record.get("minimum_current_observations") or 0)
        if minimum < 1:
            raise ValueError("drift baseline minimum_current_observations must be positive")
        if float(record["revalidation_standardized_shift"]) < float(
            record["warning_standardized_shift"]
        ):
            raise ValueError("drift revalidation threshold cannot be below warning threshold")
        validated.append(dict(record))
    return DriftBaselineRegistry(
        registry_id=registry_id,
        records=tuple(validated),
        digest_sha256=canonical_json_digest(payload),
    )


def aggregate_packet_telemetry(packets: list[dict]) -> dict:
    score_totals: dict[str, dict[str, float | int]] = {}
    bundle_ids: set[str] = set()
    bundle_digests: set[str] = set()
    valid_packets = 0
    for packet in packets:
        telemetry = packet.get("runtime_telemetry") if isinstance(packet, dict) else None
        if not isinstance(telemetry, dict) or telemetry.get("schema") != (
            "creatorproof.runtime_telemetry.v1"
        ):
            continue
        valid_packets += 1
        metadata = telemetry.get("metadata") or {}
        if metadata.get("model_bundle_id"):
            bundle_ids.add(str(metadata["model_bundle_id"]))
        if metadata.get("model_bundle_manifest_digest_sha256"):
            bundle_digests.add(str(metadata["model_bundle_manifest_digest_sha256"]))
        for name, summary in (telemetry.get("score_summaries") or {}).items():
            if not isinstance(summary, dict):
                continue
            count = int(summary.get("count") or 0)
            mean = float(summary.get("mean") or 0.0)
            if count <= 0 or not math.isfinite(mean):
                continue
            row = score_totals.setdefault(name, {"count": 0, "sum": 0.0})
            row["count"] = int(row["count"]) + count
            row["sum"] = float(row["sum"]) + mean * count
    return {
        "packet_count": len(packets),
        "valid_telemetry_packet_count": valid_packets,
        "model_bundle_ids": sorted(bundle_ids),
        "model_bundle_manifest_digests": sorted(bundle_digests),
        "score_summaries": {
            name: {
                "count": int(row["count"]),
                "mean": float(row["sum"]) / max(int(row["count"]), 1),
            }
            for name, row in sorted(score_totals.items())
        },
    }


def evaluate_runtime_drift(
    aggregate: dict,
    registry: DriftBaselineRegistry,
) -> dict:
    if not registry.records:
        return {
            "schema": "creatorproof.runtime_drift_evaluation.v1",
            **registry.status(),
            "state": "NOT_CONFIGURED",
            "revalidation_required": False,
            "reason_codes": ["AUTHORIZED_DRIFT_BASELINE_NOT_CONFIGURED"],
            "checks": [],
        }
    checks: list[dict] = []
    reasons: list[str] = []
    observed_ids = set(aggregate.get("model_bundle_ids") or [])
    observed_digests = set(aggregate.get("model_bundle_manifest_digests") or [])
    summaries = aggregate.get("score_summaries") or {}
    for record in registry.records:
        identity_matches = observed_ids == {record["model_bundle_id"]} and observed_digests == {
            record["model_bundle_manifest_digest_sha256"]
        }
        summary = summaries.get(record["score_name"]) or {}
        count = int(summary.get("count") or 0)
        current_mean = summary.get("mean")
        enough = count >= int(record["minimum_current_observations"])
        scale = max(float(record["baseline_standard_deviation"]), 1e-6)
        shift = (
            abs(float(current_mean) - float(record["baseline_mean"])) / scale
            if current_mean is not None and math.isfinite(float(current_mean))
            else None
        )
        if not identity_matches:
            state = "REVALIDATION_REQUIRED"
            reason = "MODEL_BUNDLE_IDENTITY_DRIFT"
        elif not enough:
            state = "INSUFFICIENT_CURRENT_OBSERVATIONS"
            reason = "DRIFT_SAMPLE_GATE_NOT_MET"
        elif shift is not None and shift >= float(record["revalidation_standardized_shift"]):
            state = "REVALIDATION_REQUIRED"
            reason = "SCORE_DISTRIBUTION_SHIFT_EXCEEDS_REVALIDATION_THRESHOLD"
        elif shift is not None and shift >= float(record["warning_standardized_shift"]):
            state = "WARNING"
            reason = "SCORE_DISTRIBUTION_SHIFT_WARNING"
        else:
            state = "STABLE"
            reason = None
        if reason:
            reasons.append(reason)
        checks.append(
            {
                "lane": record["lane"],
                "score_name": record["score_name"],
                "state": state,
                "reason_code": reason,
                "identity_matches": identity_matches,
                "current_observation_count": count,
                "minimum_current_observations": int(record["minimum_current_observations"]),
                "baseline_mean": float(record["baseline_mean"]),
                "current_mean": current_mean,
                "standardized_mean_shift": round(shift, 6) if shift is not None else None,
            }
        )
    revalidation = any(row["state"] == "REVALIDATION_REQUIRED" for row in checks)
    warning = any(row["state"] == "WARNING" for row in checks)
    insufficient = any(row["state"] == "INSUFFICIENT_CURRENT_OBSERVATIONS" for row in checks)
    return {
        "schema": "creatorproof.runtime_drift_evaluation.v1",
        **registry.status(),
        "state": (
            "REVALIDATION_REQUIRED"
            if revalidation
            else "WARNING"
            if warning
            else "INSUFFICIENT_CURRENT_OBSERVATIONS"
            if insufficient
            else "STABLE"
        ),
        "revalidation_required": revalidation,
        "reason_codes": sorted(set(reasons)),
        "checks": checks,
        "semantics": "DRIFT_TRIGGER_NOT_MODEL_ACCURACY_OR_CAUSAL_DIAGNOSIS",
    }
