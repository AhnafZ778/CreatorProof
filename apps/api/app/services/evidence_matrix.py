"""Immutable lane-by-lane evidence; scores retain their original semantics."""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import EvidenceCoverage, EvidenceMatrix, EvidenceSignal, Scan
from app.services.canonical import canonical_digest
from app.services.provenance_records import normalized_status

LANES = (
    "COPY",
    "ORIGIN",
    "PROVENANCE",
    "CREATOR_PROFILE",
    "RIGHTS",
    "POLICY",
    "SOURCE_COVERAGE",
    "INTEGRITY",
)


def _number(value: Any) -> float | None:
    return (
        float(value)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
        else None
    )


def normalized_signals(packet: dict, *, failed: bool = False) -> list[dict]:
    """Pure projection. No score averaging or generated correspondence."""
    scope = packet.get("scope") or {}
    bundle = packet.get("model_bundle") or {}
    decision = packet.get("decision") or {}
    result: list[dict] = []

    def add(
        lane,
        kind,
        provider,
        state,
        payload=None,
        score=None,
        semantics=None,
        quality="DESCRIPTIVE",
        artifacts=None,
        coverage=None,
        reasons=None,
        fallback=False,
        identifier=None,
    ):
        payload = payload or {}
        result.append(
            {
                "lane": lane,
                "signal_type": kind,
                "provider": provider or "unknown",
                "provider_version": payload.get("provider_version") or payload.get("model_version"),
                "status": state,
                "score": _number(score),
                "score_semantics": semantics,
                "confidence": None,
                "confidence_level": "DIRECT"
                if quality == "DIRECT"
                else "INCONCLUSIVE"
                if state in {"INCONCLUSIVE", "ERROR", "PROVIDER_UNAVAILABLE"}
                else "DESCRIPTIVE",
                "evidence_quality": quality,
                "coverage_status": "COMPLETE"
                if state in {"SUPPORTED", "NOT_APPLICABLE"}
                else "UNAVAILABLE"
                if state in {"NOT_RUN", "ERROR", "PROVIDER_UNAVAILABLE"}
                else "PARTIAL",
                "coverage": coverage or {},
                "reason_codes": reasons
                if reasons is not None
                else list(payload.get("reason_codes") or []),
                "artifact_refs": artifacts or [],
                "error_code": payload.get("error_code"),
                "fallback_used": fallback,
                "model_version": payload.get("model_version"),
                "rule_version": identifier,
                "model_or_rule_identifier": identifier or payload.get("model_version") or kind,
            }
        )

    if failed:
        for lane in LANES:
            add(
                lane,
                "PIPELINE_FAILURE",
                "creatorproof",
                "ERROR" if lane == "POLICY" else "NOT_RUN",
                reasons=list(decision.get("reason_codes") or ["PIPELINE_ERROR"]),
            )
        return result

    matches = packet.get("matches") or []
    for index, match in enumerate(matches):
        geometry = match.get("geometry") or {}
        fusion = match.get("fusion") or {}
        aligned = match.get("aligned_perceptual") or {}
        exact = bool(match.get("exact_sha256"))
        valid_geometry = (
            bool(geometry.get("validated")) or geometry.get("alignment_grade") == "STRICT"
        )
        relaxed = geometry.get("alignment_grade") == "CORROBORATION_REQUIRED"
        validated_copy = bool(fusion.get("match_supported"))
        ref = {"work_id": match.get("work_id"), "packet_pointer": f"/matches/{index}"}
        add(
            "COPY",
            "EXACT_HASH",
            "sha256",
            "SUPPORTED" if exact else "NOT_APPLICABLE",
            quality="DIRECT",
            coverage=ref,
            semantics="BYTE_IDENTITY_BOOLEAN",
        )
        add(
            "COPY",
            "RETRIEVAL",
            match.get("retrieval_provider"),
            "INCONCLUSIVE",
            match,
            match.get("retrieval_score"),
            "RETRIEVAL_RANKING_NOT_COPY_PROBABILITY",
            coverage=ref,
        )
        regions = (match.get("visualization") or {}).get("regions") or []
        refs = (
            [
                {"packet_pointer": f"/matches/{index}/visualization/regions/{i}"}
                for i, _ in enumerate(regions)
            ]
            if valid_geometry or (relaxed and validated_copy)
            else []
        )
        add(
            "COPY",
            "GEOMETRY",
            bundle.get("geometric_verifier"),
            "SUPPORTED" if valid_geometry else "INCONCLUSIVE",
            geometry,
            geometry.get("inlier_ratio"),
            "DESCRIPTIVE_INLIER_RATIO",
            coverage=ref,
            artifacts=refs,
            reasons=list(geometry.get("rejection_reasons") or []),
        )
        add(
            "COPY",
            "ALIGNED_PERCEPTUAL",
            bundle.get("aligned_perceptual_verifier"),
            "SUPPORTED" if aligned.get("available") and (valid_geometry or relaxed) else "NOT_RUN",
            aligned,
            aligned.get("structure_consensus"),
            "ALIGNED_STRUCTURE_NOT_PROBABILITY",
            coverage=ref,
        )
        add(
            "COPY",
            "COPY_FUSION",
            bundle.get("fusion") or "copy-fusion",
            "SUPPORTED"
            if validated_copy
            else "INCONCLUSIVE"
            if fusion.get("review_supported")
            else "UNSUPPORTED",
            fusion,
            fusion.get("evidence_index"),
            "COPY_EVIDENCE_INDEX_NOT_PROBABILITY",
            coverage=ref,
            artifacts=refs,
            identifier=bundle.get("fusion"),
        )
    if not matches:
        complete = scope.get("coverage_status") == "COMPLETE"
        add(
            "COPY",
            "NO_VALIDATED_COPY_REGION",
            bundle.get("retrieval_provider"),
            "SUPPORTED" if complete else "INCONCLUSIVE",
            coverage=scope,
            reasons=["NO_VALIDATED_COPY_REGION", "SOURCE_SCOPED_RESULT"],
        )

    origin = packet.get("synthetic_origin") or {}
    classification = origin.get("classification") or "SYNTHETIC_ORIGIN_ANALYSIS_UNAVAILABLE"
    members = origin.get("members") or []
    for member in members:
        add(
            "ORIGIN",
            "DETECTOR_OUTPUT",
            member.get("provider"),
            "SUPPORTED",
            member,
            member.get("score", member.get("raw_score")),
            member.get("score_semantics") or "MODEL_RESPONSE_NOT_PROBABILITY",
            fallback=bool((origin.get("routing") or {}).get("fallback_activated")),
        )
    origin_supported = classification in {
        "AI_PROVENANCE_CONFIRMED",
        "LIKELY_AI_GENERATED",
        "AI_INDICATORS_CORROBORATED",
        "AI_ORIGIN_MARKER_FOUND",
        "NO_AI_ORIGIN_EVIDENCE_DETECTED",
    }
    add(
        "ORIGIN",
        "ORIGIN_ASSESSMENT",
        bundle.get("synthetic_origin_provider"),
        "SUPPORTED" if origin_supported else "INCONCLUSIVE" if members else "PROVIDER_UNAVAILABLE",
        origin,
        origin.get("fused_detector_score"),
        origin.get("score_semantics"),
        identifier=bundle.get("synthetic_origin_fusion"),
    )
    marker = origin.get("visible_marker_signal") or {}
    add(
        "ORIGIN",
        "VISIBLE_MARKER",
        marker.get("provider"),
        "SUPPORTED" if marker.get("checked") else "PROVIDER_UNAVAILABLE",
        marker,
    )

    provenance = packet.get("provenance") or {}
    state = normalized_status(provenance.get("status"), list(provenance.get("reason_codes") or []))
    add(
        "PROVENANCE",
        "C2PA_INSPECTION",
        provenance.get("provider"),
        {
            "VALID": "SUPPORTED",
            "VALID_BUT_UNTRUSTED": "SUPPORTED",
            "ABSENT": "INCONCLUSIVE",
            "INVALID": "ERROR",
            "UNSUPPORTED": "UNSUPPORTED",
            "PROVIDER_UNAVAILABLE": "PROVIDER_UNAVAILABLE",
            "PARSE_ERROR": "ERROR",
        }[state],
        provenance,
        quality="DIRECT",
        coverage={"normalized_status": state},
    )
    style = packet.get("style_analysis") or {}
    style_decision = style.get("decision") or {}
    add(
        "CREATOR_PROFILE",
        "STYLE_RESEMBLANCE",
        style.get("provider"),
        "INCONCLUSIVE" if style.get("top_profiles") else "NOT_APPLICABLE",
        style,
        semantics="STYLE_ADVISORY_NOT_ARTIST_IDENTITY",
        coverage={"classification": style_decision.get("classification")},
    )
    rights = (decision.get("policy_inputs") or {}).get("rights_facts") or {}
    add(
        "RIGHTS",
        "RECORDED_RIGHTS_FACTS",
        "creatorproof-rights",
        "SUPPORTED" if rights else "NOT_RUN",
        rights,
        coverage={
            "missing_facts": rights.get("missing_facts") or [],
            "authorizing_license_id": rights.get("authorizing_license_id"),
        },
        reasons=list(rights.get("claim_reason_codes") or [])
        + list(rights.get("license_reason_codes") or []),
    )
    add(
        "POLICY",
        "DETERMINISTIC_POLICY",
        "creatorproof-policy-engine",
        "SUPPORTED" if decision.get("policy_action") else "NOT_RUN",
        decision,
        semantics="PUBLICATION_POLICY_NOT_LEGAL_CONCLUSION",
        identifier=decision.get("policy_digest_sha256"),
    )
    add(
        "SOURCE_COVERAGE",
        "CORPUS_SCOPE",
        "creatorproof-corpus",
        "SUPPORTED" if scope.get("coverage_status") == "COMPLETE" else "INCONCLUSIVE",
        scope,
        coverage=scope,
        reasons=list(scope.get("coverage_reason_codes") or []),
    )
    proof = packet.get("proof") or {}
    add(
        "INTEGRITY",
        "PACKET_COMMITMENT",
        "sha256",
        "SUPPORTED" if proof.get("packet_hash_sha256") else "NOT_RUN",
        semantics="PACKET_IDENTITY_NOT_OWNERSHIP",
        quality="DIRECT",
        coverage={"packet_hash_sha256": proof.get("packet_hash_sha256")},
    )
    return result


def matrix_summary(packet: dict, signals: list[dict], *, failed: bool = False) -> dict:
    decision = packet.get("decision") or {}
    origin = packet.get("synthetic_origin") or {}
    match_status = decision.get("match_status")
    copy_supported = match_status == "MATCH_FOUND"
    coverage = packet.get("scope") or {}
    incomplete = coverage.get("coverage_status") != "COMPLETE"
    optional_missing = any(
        row["status"] in {"PROVIDER_UNAVAILABLE", "ERROR", "NOT_RUN"} for row in signals
    )
    contradictory = origin.get("classification") == "INCONCLUSIVE_DETECTOR_DISAGREEMENT"
    if failed:
        final = "PROVIDER_FAILURE"
    elif contradictory:
        final = "CONTRADICTORY"
    elif incomplete and not copy_supported:
        final = "INSUFFICIENT_COVERAGE"
    elif match_status == "INCONCLUSIVE":
        final = "INCONCLUSIVE"
    elif copy_supported and optional_missing:
        final = "PARTIALLY_SUPPORTED"
    elif copy_supported:
        final = "SUPPORTED"
    elif optional_missing:
        final = "PARTIALLY_SUPPORTED"
    else:
        final = "SUPPORTED"
    abstain = final in {
        "PROVIDER_FAILURE",
        "CONTRADICTORY",
        "INSUFFICIENT_COVERAGE",
        "INCONCLUSIVE",
    }
    reasons = sorted(
        set(
            list(decision.get("reason_codes") or [])
            + list(coverage.get("coverage_reason_codes") or [])
            + (["DETECTOR_ENSEMBLE_DISAGREEMENT"] if contradictory else [])
        )
    )
    return {
        "final_status": final,
        "abstention": abstain,
        "abstention_code": final if abstain else None,
        "reason": "; ".join(reasons) or "Lane-scoped evidence; no legal conclusion.",
        "recommended_action": "HUMAN_REVIEW"
        if abstain
        else decision.get("policy_action", "REVIEW"),
        "coverage_summary": {
            **coverage,
            "lanes": {
                lane: {
                    "signals": sum(row["lane"] == lane for row in signals),
                    "states": sorted({row["status"] for row in signals if row["lane"] == lane}),
                }
                for lane in LANES
            },
        },
    }


def persist_evidence_matrix(
    db: Session,
    *,
    scan: Scan,
    packet: dict,
    failed: bool = False,
    correction_reason: str | None = None,
) -> EvidenceMatrix:
    existing = db.scalar(
        select(EvidenceMatrix)
        .where(EvidenceMatrix.tenant_id == scan.tenant_id, EvidenceMatrix.scan_id == scan.id)
        .order_by(EvidenceMatrix.created_at.desc())
        .limit(1)
    )
    if existing is not None and correction_reason is None:
        return existing
    signals = normalized_signals(packet, failed=failed)
    summary = matrix_summary(packet, signals, failed=failed)
    completed = datetime.now(UTC)
    if correction_reason:
        summary["reason"] = f"Correction: {correction_reason}; {summary['reason']}"
    matrix = EvidenceMatrix(
        tenant_id=scan.tenant_id,
        scan_id=scan.id,
        version=existing.version + 1 if existing else 1,
        previous_matrix_id=existing.id if existing else None,
        **summary,
        policy_decision_id=(packet.get("decision") or {}).get("policy_version_id"),
        packet_hash_sha256=(packet.get("proof") or {}).get("packet_hash_sha256")
        or canonical_digest(packet),
        finalized_at=completed,
    )
    db.add(matrix)
    db.flush()
    for index, signal in enumerate(signals):
        identity = {"matrix": matrix.id, "scan": scan.id, "index": index, "signal": signal}
        row = EvidenceSignal(
            signal_id=f"sig_{canonical_digest(identity)}",
            tenant_id=scan.tenant_id,
            scan_id=scan.id,
            matrix_id=matrix.id,
            **signal,
            input_sha256=scan.candidate_sha256,
            started_at=scan.created_at,
            completed_at=completed,
        )
        db.add(row)
    for lane, state in summary["coverage_summary"]["lanes"].items():
        unavailable = [
            row["signal_type"]
            for row in signals
            if row["lane"] == lane and row["status"] in {"ERROR", "NOT_RUN", "PROVIDER_UNAVAILABLE"}
        ]
        db.add(
            EvidenceCoverage(
                tenant_id=scan.tenant_id,
                scan_id=scan.id,
                matrix_id=matrix.id,
                lane=lane,
                provider="packet-projection",
                requested_scope={"lane": lane},
                completed_scope=state,
                unavailable_scope={"signals": unavailable},
                coverage_percent=100.0
                if all(
                    row["coverage_status"] == "COMPLETE" for row in signals if row["lane"] == lane
                )
                and state["signals"]
                else None,
                reason_codes=["LANE_INCOMPLETE"] if unavailable else [],
            )
        )
    db.flush()
    return matrix
