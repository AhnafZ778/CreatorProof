"""Shared, evidence-based boundary between scan results and operator review.

The queue is a view of persisted scans, not a second copy of the detector result.
Coverage gaps are review work, but never a finding that an image was misused.
"""

from __future__ import annotations

from collections.abc import Mapping

POSITIVE_ORIGIN_CLASSIFICATIONS = frozenset(
    {
        "AI_PROVENANCE_CONFIRMED",
        "LIKELY_AI_GENERATED",
        "AI_INDICATORS_CORROBORATED",
        "AI_ORIGIN_MARKER_FOUND",
        "AI_ORIGIN_REVIEW_CANDIDATE",
        "AI_PROVENANCE_ASSERTED_UNTRUSTED_SIGNER",
    }
)


def _packet(scan) -> dict:
    packet = getattr(scan, "evidence_packet", None)
    if hasattr(packet, "model_dump"):
        packet = packet.model_dump(by_alias=True)
    return packet if isinstance(packet, dict) else {}


def positive_origin(packet: dict) -> bool:
    origin = packet.get("synthetic_origin") or {}
    if not isinstance(origin, Mapping):
        return False
    return str(origin.get("classification") or "").upper() in POSITIVE_ORIGIN_CLASSIFICATIONS


def review_signal(scan) -> dict:
    """Describe a stored scan's human-review need without inventing detector flags."""
    state = str(getattr(scan, "state", "") or "")
    if state != "COMPLETED":
        return {
            "saved": True,
            "status": "unavailable" if state == "FAILED" else "pending",
            "category": None,
            "reasons": [],
        }
    packet = _packet(scan)
    reasons: list[str] = []
    content_flag = False
    if str(getattr(scan, "match_status", "")) == "MATCH_FOUND":
        reasons.append("CATALOG_MATCH")
        content_flag = True
    elif str(getattr(scan, "match_status", "")) == "INCONCLUSIVE":
        reasons.append("COPY_EVIDENCE_INCONCLUSIVE")
        content_flag = True
    if positive_origin(packet):
        reasons.append("AI_ORIGIN_INDICATORS")
        content_flag = True
    style = packet.get("style_analysis") or {}
    decision = (style.get("decision") or {}) if isinstance(style, Mapping) else {}
    if (
        isinstance(style, Mapping)
        and style.get("learned_provider_active") is True
        and isinstance(decision, Mapping)
        and decision.get("review_recommended") is True
    ):
        reasons.append("CREATOR_RESEMBLANCE")
        content_flag = True
    action = str(getattr(scan, "policy_action", "") or "")
    if action in {"REVIEW", "BLOCK"}:
        reasons.append(f"POLICY_{action}")
    if not reasons:
        return {"saved": True, "status": "not_flagged", "category": None, "reasons": []}
    return {
        "saved": True,
        "status": "needs_review",
        "category": "CONTENT_FLAG" if content_flag else "ASSESSMENT_GAP",
        "reasons": reasons,
    }


def copyright_draft_block_reason(scan, work=None, review_case=None) -> str | None:
    """Copyright drafting requires a real, unresolved catalog match and its work."""
    if scan is None or str(scan.state) != "COMPLETED" or scan.match_status != "MATCH_FOUND":
        return "A copyright notice requires a completed match to a registered work."
    if work is None or work.deleted_at is not None:
        return "The matched registered work is unavailable; verify the rights evidence first."
    if (
        review_case is not None
        and review_case.state in {"RESOLVED", "CLOSED"}
        and review_case.disposition == "APPROVED_FOR_PUBLICATION"
    ):
        return (
            "The operator approved publication for this case; "
            "reopen review before drafting a notice."
        )
    decision = _packet(scan).get("decision") or {}
    if scan.policy_action == "PASS_BY_POLICY" or (
        isinstance(decision, Mapping) and decision.get("authorizing_license_id")
    ):
        return "The recorded policy or license authorizes this use; review permission first."
    return None
