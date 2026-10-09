"""Measured ratings retain their units and never become infringement probabilities."""

from __future__ import annotations

import math

from sqlalchemy import select


def _unit_score(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) and 0 <= value <= 1 else None


def attach_ratings(packet: dict, assessment: dict) -> dict:
    from app.services.evidence import canonical_hash

    lanes = assessment["lanes"]
    matches = packet.get("matches") or []
    selected = next((m for m in matches if m.get("exact_sha256")), None)
    selected = selected or next(
        (m for m in matches if (m.get("fusion") or {}).get("match_supported")), None
    )
    selected = selected or (matches[0] if matches else {})

    def rating(
        key,
        display,
        label,
        grade,
        *,
        value=None,
        scale=None,
        basis=None,
        conclusive=False,
        tone="neutral",
    ):
        lanes[key]["rating"] = {
            "display": display,
            "label": label,
            "grade": grade,
            "value": value,
            "scale": scale,
            "basis": basis,
            "conclusive": conclusive,
            "tone": tone,
        }

    def index(key, score, label, grade, **facts):
        value = _unit_score(score)
        if value is None:
            rating(key, "—", label, "Not measured")
        else:
            rating(key, f"{value * 100:.1f}", label, grade, value=value * 100, scale=100, **facts)

    for key in lanes:
        rating(key, "—", "No completed measurement", "Not measured")
    if lanes["COPY"]["status"] != "ERROR":
        exact = lanes["COPY"]["verdict"] == "EXACT_COPY"
        conclusive = lanes["COPY"]["verdict"] in {"EXACT_COPY", "VALIDATED_REUSE"}
        index(
            "COPY",
            1.0 if exact else (selected.get("fusion") or {}).get("evidence_index"),
            "Byte identity" if exact else "Copy evidence index",
            "Exact match" if exact else "Confirmed reuse" if conclusive else "Candidate only",
            conclusive=conclusive,
            tone="good" if conclusive else "neutral",
            basis="SHA256_IDENTITY" if exact else "COPY_FUSION_INDEX_NOT_PROBABILITY",
        )
    origin = packet.get("synthetic_origin") or {}
    if lanes["ORIGIN"]["status"] not in {"ERROR", "NOT_RUN", "PROVIDER_UNAVAILABLE"}:
        score = origin.get("fused_detector_score")
        index(
            "ORIGIN",
            score,
            "AI detector score",
            (origin.get("scorecard") or {}).get("signal_label") or "Model assessed",
            basis=origin.get("score_semantics") or "MODEL_OUTPUT_NOT_PROBABILITY",
        )
        if lanes["ORIGIN"]["verdict"] == "AI_PROVENANCE_CONFIRMED":
            rating(
                "ORIGIN",
                "AI",
                "Trusted generation declaration",
                "Provenance confirmed",
                conclusive=True,
                tone="good",
                basis="TRUSTED_PROVENANCE_DECLARATION",
            )
    provenance = lanes["PROVENANCE"]["verdict"]
    if provenance in {"VALID", "VALID_BUT_UNTRUSTED", "ABSENT"}:
        rating(
            "PROVENANCE",
            "0" if provenance == "ABSENT" else "Valid",
            "Embedded credentials found" if provenance == "ABSENT" else "Credential validation",
            "Inspection complete"
            if provenance == "ABSENT"
            else "Trust verified"
            if provenance == "VALID"
            else "Signer untrusted",
            value=0 if provenance == "ABSENT" else None,
            conclusive=provenance in {"VALID", "ABSENT"},
            tone="good" if provenance == "VALID" else "neutral",
            basis="C2PA_INSPECTION",
        )
    elif provenance == "INVALID":
        rating(
            "PROVENANCE",
            "Invalid",
            "Credential validation",
            "Validation failed",
            tone="bad",
            basis="C2PA_INSPECTION",
        )
    elif provenance == "PARSE_ERROR":
        rating(
            "PROVENANCE",
            "Error",
            "Credential inspection",
            "Inspection failed",
            tone="bad",
            basis="C2PA_INSPECTION",
        )
    style = packet.get("style_analysis") or {}
    style_decision = style.get("decision") or {}
    if style.get("top_profiles") and lanes["CREATOR_PROFILE"]["status"] != "ERROR":
        index(
            "CREATOR_PROFILE",
            style_decision.get("evidence_index"),
            "Style similarity index",
            "Measured resemblance",
            basis=style_decision.get("score_semantics"),
        )
    rights = ((packet.get("decision") or {}).get("policy_inputs") or {}).get("rights_facts") or {}
    matched_ids = lanes["COPY"].get("work_ids") or []
    if rights.get("work_id") in matched_ids and lanes["RIGHTS"]["status"] != "ERROR":
        count = len(set(rights.get("strongly_authorizing_license_ids") or []))
        if rights.get("authorizing_license_id") and rights.get("authorized"):
            count = max(count, 1)
        rating(
            "RIGHTS",
            str(count),
            "Authorizing licenses on record",
            "License on file" if count else "No license on file",
            value=count,
            basis="RECORDED_PERMISSION_SNAPSHOT",
            tone="good" if count else "neutral",
        )
        if lanes["RIGHTS"]["verdict"] == "PERMISSION_CONFLICT":
            rating(
                "RIGHTS",
                "Conflict",
                "Declared use versus artist preferences",
                "Permission conflict",
                basis="RECORDED_PERMISSION_SNAPSHOT",
                tone="bad",
            )
    policy = (packet.get("decision") or {}).get("policy_action")
    if policy in {"REVIEW", "BLOCK", "PASS_BY_POLICY"} and lanes["POLICY"]["status"] != "ERROR":
        rating(
            "POLICY",
            "PASS" if policy == "PASS_BY_POLICY" else policy,
            "Recorded publication decision",
            "Operator approval" if policy == "REVIEW" else "Policy applied",
            conclusive=True,
            basis="DETERMINISTIC_POLICY_NOT_LEGAL_CONCLUSION",
            tone="bad"
            if policy == "BLOCK"
            else "good"
            if policy == "PASS_BY_POLICY"
            else "neutral",
        )
    scope = packet.get("scope") or {}
    if lanes["SOURCE_COVERAGE"]["status"] != "ERROR":
        total = scope.get("eligible_reference_count")
        checked = max(
            (
                cap.get("references_checked", 0)
                for cap in (scope.get("capabilities") or {}).values()
                if isinstance(cap, dict)
            ),
            default=0,
        )
        if isinstance(total, int) and not isinstance(total, bool) and total > 0:
            checked = min(checked, total)
            rating(
                "SOURCE_COVERAGE",
                f"{checked} / {total}",
                "Registered references checked",
                "Scope complete"
                if scope.get("coverage_status") == "COMPLETE"
                else "Partial coverage",
                value=checked,
                scale=total,
                conclusive=scope.get("coverage_status") == "COMPLETE",
                basis="DECLARED_CORPUS_ONLY",
            )
    proof = packet.get("proof") or {}
    digest = proof.get("packet_hash_sha256")
    verified = (
        bool(digest) and canonical_hash({k: v for k, v in packet.items() if k != "proof"}) == digest
    )
    if lanes["INTEGRITY"]["status"] != "ERROR" and verified:
        rating(
            "INTEGRITY",
            "SHA-256",
            "Saved packet integrity",
            "Hash verified",
            conclusive=True,
            tone="good",
            basis="RECOMPUTED_CANONICAL_PACKET_HASH",
        )
    elif lanes["INTEGRITY"]["status"] != "ERROR" and digest:
        rating(
            "INTEGRITY",
            "Mismatch",
            "Saved packet integrity",
            "Verification failed",
            tone="bad",
            basis="RECOMPUTED_CANONICAL_PACKET_HASH",
        )
    assessment["rating_semantics"] = (
        "Scores describe their named model index; "
        "they are not confidence or infringement probabilities."
    )
    return assessment


def resolve_assessment_scan(db, scan):
    """Reject cross-tenant, wrong-image, changed-reference or uncommitted links."""
    from app.models import ReviewCase, Scan
    from app.services.evidence import canonical_hash

    case = db.scalar(
        select(ReviewCase).where(
            ReviewCase.scan_id == scan.id,
            ReviewCase.tenant_id == scan.tenant_id,
        )
    )
    archive = case.archive_record if case and case.archive_record else {}
    source_id = archive.get("assessment_scan_id")
    if not source_id:
        return scan
    source = db.scalar(select(Scan).where(Scan.id == source_id, Scan.tenant_id == scan.tenant_id))
    if source is None or source.state != "COMPLETED" or source.catalog_id != scan.catalog_id:
        return scan
    if source.match_status == "MATCH_FOUND" and source.top_match_work_id != archive.get("work_id"):
        return scan
    if (
        source.candidate_sha256 != scan.candidate_sha256
        or archive.get("candidate_sha256") != scan.candidate_sha256
    ):
        return scan
    packet = source.evidence_packet or {}
    commitment = (packet.get("proof") or {}).get("packet_hash_sha256")
    if (
        not commitment
        or canonical_hash({k: v for k, v in packet.items() if k != "proof"}) != commitment
    ):
        return scan
    manifest = (packet.get("scope") or {}).get("catalog_manifest") or []
    if not any(
        row.get("work_id") == archive.get("work_id")
        and row.get("sha256") == archive.get("reference_sha256")
        for row in manifest
    ):
        return scan
    return source
