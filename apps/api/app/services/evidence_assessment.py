"""Explain saved model conclusions without changing immutable signal receipts.

Positive evidence, negative findings and missing checks have different meanings.
Permissions are evaluated separately from visual reuse; neither AI origin nor
creator resemblance establishes unauthorized use.
"""

from __future__ import annotations

from typing import Any

from app.services.provenance_records import normalized_status

ASSESSMENT_VERSION = "creatorproof.evidence-assessment.v1"


def _dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _rows(value: Any) -> list[dict]:
    return [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []


def assess_evidence_packet(packet: dict, signals: list[dict], *, failed: bool = False) -> dict:
    """A versioned read projection of recorded assessments, never new inference."""
    packet = _dict(packet)
    decision = _dict(packet.get("decision"))
    scope = _dict(packet.get("scope"))
    matches = _rows(packet.get("matches"))
    lanes: dict[str, dict] = {}

    def lane(key, verdict, label, explanation, status="SUPPORTED", tone=None, **facts):
        rows = [row for row in signals if row.get("lane") == key]
        lanes[key] = {
            "verdict": verdict,
            "label": label,
            "explanation": explanation,
            "status": status,
            "tone": tone or ("good" if status == "SUPPORTED" else "review"),
            "evidence_signal_ids": [row["signal_id"] for row in rows if row.get("signal_id")],
            "reason_codes": sorted(
                {
                    code
                    for row in rows
                    for code in row.get("reason_codes", [])
                    if isinstance(code, str)
                }
            ),
            **facts,
        }

    exact = [match for match in matches if match.get("exact_sha256") is True]
    supported = [
        match for match in matches if _dict(match.get("fusion")).get("match_supported") is True
    ]
    confirmed = decision.get("match_status") == "MATCH_FOUND" and bool(exact or supported)
    complete = scope.get("coverage_status") == "COMPLETE"
    no_match = decision.get("match_status") == "NO_MATCH_IN_CHECKED_SOURCES" and not (
        exact or supported
    )
    selected = (exact or supported or matches or [{}])[0]
    work_id = selected.get("work_id")
    if confirmed:
        geometry = _dict(selected.get("geometry"))
        fusion = _dict(selected.get("fusion"))
        lane(
            "COPY",
            "EXACT_COPY" if exact else "VALIDATED_REUSE",
            "Exact copy confirmed" if exact else "Visual reuse supported",
            "The submitted file and registered artwork have identical SHA-256 hashes."
            if exact
            else "The copy verifier supports reuse of the registered artwork through "
            "validated correspondence and aligned image evidence.",
            work_ids=[work_id] if work_id else [],
            model_classification=fusion.get("classification"),
            metrics={
                "verified_feature_pairs": geometry.get("inliers"),
                "inlier_ratio": geometry.get("inlier_ratio"),
                "evidence_index": fusion.get("evidence_index"),
                "score_semantics": "COPY_EVIDENCE_INDEX_NOT_PROBABILITY",
            },
            limitations=["Visual reuse alone does not establish whether permission was granted."],
        )
    elif no_match and complete:
        lane(
            "COPY",
            "NO_SUPPORTED_REUSE",
            "No supported reuse found",
            "No registered artwork match was supported in the checked sources.",
            limitations=["This result does not cover artworks outside the checked corpus."],
        )
    else:
        conflict = bool(exact or supported)
        lane(
            "COPY",
            "CONFLICTING_REUSE_RESULTS" if conflict else "REUSE_UNRESOLVED",
            "Reuse results need review" if conflict else "Reuse not established",
            (
                "The match decision and individual positive results disagree. Review the "
                "saved evidence."
            )
            if conflict
            else "Candidate similarity did not establish a validated artwork match."
            if matches
            else "No completed, sufficiently covered reuse assessment is available.",
            status="INCONCLUSIVE",
        )

    origin = _dict(packet.get("synthetic_origin"))
    origin_class = origin.get("classification")
    origin_outcomes = {
        "AI_PROVENANCE_CONFIRMED": (
            "AI provenance confirmed",
            "Trusted provenance records declare AI generation.",
        ),
        "LIKELY_AI_GENERATED": (
            "Likely AI generated",
            "The recorded detector ensemble supports a likely AI-origin finding.",
        ),
        "AI_INDICATORS_CORROBORATED": (
            "AI indicators corroborated",
            "Independent recorded signals corroborate AI-origin indicators.",
        ),
        "AI_ORIGIN_MARKER_FOUND": (
            "AI marker detected",
            "An AI-origin marker was detected; a visible marker alone is not proof of generation.",
        ),
        "NO_AI_ORIGIN_EVIDENCE_DETECTED": (
            "No AI indicators detected",
            (
                "The completed origin assessment found no supporting AI indicators; this "
                "does not prove human authorship."
            ),
        ),
    }
    if origin_class in origin_outcomes:
        label, explanation = origin_outcomes[origin_class]
        lane(
            "ORIGIN",
            origin_class,
            label,
            explanation,
            model_classification=origin_class,
            limitations=[
                "AI origin alone does not establish reuse or misuse of this artist's artwork."
            ],
        )
    else:
        origin_gaps = {
            "INCONCLUSIVE_DETECTOR_DISAGREEMENT": (
                "AI detectors disagree",
                "The recorded detectors disagree; an AI-origin conclusion is not supported.",
            ),
            "INCONCLUSIVE_LOW_RESOLUTION": (
                "Image too small for AI assessment",
                "Image resolution limited the recorded detectors.",
            ),
            "INCONCLUSIVE_TRANSFORM_INSTABILITY": (
                "AI result unstable across edits",
                "Detector results were unstable across the checked transformations.",
            ),
            "AI_PROVENANCE_ASSERTED_UNTRUSTED_SIGNER": (
                "AI claim from untrusted signer",
                "Provenance asserts AI generation, but signer trust was not established.",
            ),
            "AI_ORIGIN_REVIEW_CANDIDATE": (
                "AI indicators need review",
                "The recorded origin indicators did not meet the ensemble's supported threshold.",
            ),
            "AI_ORIGIN_INCONCLUSIVE_LIMITED_COVERAGE": (
                "AI coverage insufficient",
                "The recorded origin checks have insufficient independent coverage.",
            ),
        }
        label, explanation = origin_gaps.get(
            origin_class,
            (
                "AI origin not assessed",
                "No completed AI-origin assessment is available for this scan.",
            ),
        )
        lane(
            "ORIGIN",
            origin_class or "ORIGIN_NOT_RUN",
            label,
            explanation,
            status="INCONCLUSIVE" if origin_class in origin_gaps else "PROVIDER_UNAVAILABLE",
            model_classification=origin_class,
        )

    provenance = _dict(packet.get("provenance"))
    prov_state = normalized_status(
        provenance.get("status"), list(provenance.get("reason_codes") or [])
    )
    prov_outcomes = {
        "VALID": (
            "Credentials verified",
            "The recorded Content Credentials passed validation with a trusted signer.",
            "SUPPORTED",
            "good",
        ),
        "VALID_BUT_UNTRUSTED": (
            "Credentials valid; signer untrusted",
            "The credentials validated, but signer trust was not established.",
            "SUPPORTED",
            "review",
        ),
        "ABSENT": (
            "No Content Credentials found",
            (
                "The inspection found no embedded credentials. Absence does not establish "
                "stripping or AI authorship."
            ),
            "SUPPORTED",
            "neutral",
        ),
        "INVALID": (
            "Credentials invalid",
            "The recorded inspection reported invalid Content Credentials.",
            "ERROR",
            "bad",
        ),
        "UNSUPPORTED": (
            "Credential format unsupported",
            "The configured inspector could not assess this credential format.",
            "UNSUPPORTED",
            "review",
        ),
        "PROVIDER_UNAVAILABLE": (
            "Provenance not assessed",
            "No available provenance inspector completed this check.",
            "PROVIDER_UNAVAILABLE",
            "review",
        ),
        "PARSE_ERROR": (
            "Credential inspection failed",
            "The inspector could not parse the credentials; no provenance finding is established.",
            "ERROR",
            "review",
        ),
    }
    label, explanation, status, tone = prov_outcomes[prov_state]
    lane("PROVENANCE", prov_state, label, explanation, status, tone)

    style = _dict(packet.get("style_analysis"))
    style_decision = _dict(style.get("decision"))
    style_class = style_decision.get("classification")
    style_metrics = {
        key: style_decision.get(key)
        for key in (
            "evidence_tier",
            "evidence_index",
            "independent_support_count",
            "calibration_state",
            "false_match_control_supported",
            "score_semantics",
        )
    }
    if not style.get("top_profiles"):
        lane(
            "CREATOR_PROFILE",
            "PROFILE_NOT_ASSESSED",
            "No creator profile assessed",
            "No creator-profile comparison was completed for this scan.",
            status="NOT_RUN",
        )
    elif style_class in {
        "HIGH_STYLE_RESEMBLANCE_EVIDENCE",
        "VERY_HIGH_STYLE_RESEMBLANCE_EVIDENCE",
    } and (
        style_decision.get("learned_style_similarity") is not None
        and style_decision.get("false_match_control_supported") is True
        and not str(style.get("provider", "")).startswith("diagnostic")
    ):
        lane(
            "CREATOR_PROFILE",
            style_class,
            "Very high resemblance supported"
            if style_class.startswith("VERY_HIGH")
            else "High resemblance supported",
            "The learned style model and corroborating checks support creator-profile resemblance.",
            metrics=style_metrics,
            limitations=[
                (
                    "Style resemblance does not identify the artist or establish artwork "
                    "reuse or misuse."
                )
            ],
        )
    elif style_class == "LOW_STYLE_RESEMBLANCE_EVIDENCE":
        lane(
            "CREATOR_PROFILE",
            style_class,
            "Strong resemblance not supported",
            "The recorded style assessment did not meet its supported resemblance threshold.",
            status="UNSUPPORTED",
            tone="neutral",
            metrics=style_metrics,
        )
    else:
        diagnostic = style_class == "DIAGNOSTIC_STYLE_RESEMBLANCE_ONLY" or str(
            style.get("provider", "")
        ).startswith("diagnostic")
        lane(
            "CREATOR_PROFILE",
            style_class or "STYLE_REVIEW_REQUIRED",
            "Diagnostic resemblance only" if diagnostic else "Resemblance needs review",
            (
                "Texture and mark-making similarities were recorded, but a calibrated "
                "learned style assessment was not available."
            )
            if diagnostic
            else (
                "The recorded style assessment did not establish supported "
                "creator-profile resemblance."
            ),
            status="INCONCLUSIVE",
            metrics=style_metrics,
            limitations=[
                "A high diagnostic score is not artist attribution or evidence of misuse."
            ],
        )

    rights = _dict(_dict(decision.get("policy_inputs")).get("rights_facts"))
    preferences = _dict(rights.get("rights_preferences"))
    missing = [code for code in rights.get("missing_facts", []) if isinstance(code, str)]
    rights_aligned = bool(work_id) and rights.get("work_id") == work_id
    license_id = rights.get("authorizing_license_id")
    authorized = rights_aligned and bool(license_id) and rights.get("authorized") is True
    preference_active = preferences.get("state") == "ACTIVE"
    permission_conflicts = (
        [code for code in preferences.get("blocking_reason_codes", []) if isinstance(code, str)]
        if preference_active
        else []
    )
    denied = rights_aligned and bool(permission_conflicts)
    requires_license = (
        rights_aligned
        and preference_active
        and (
            preferences.get("license_required") is True
            or preferences.get("preference") == "LICENSE_REQUIRED"
        )
    )
    if not confirmed:
        lane(
            "RIGHTS",
            "NO_CONFIRMED_WORK",
            "No confirmed artwork to authorize",
            "Resolve the artwork match before applying its permissions to this image.",
            status="NOT_APPLICABLE",
            tone="neutral",
        )
    elif not rights_aligned:
        lane(
            "RIGHTS",
            "RIGHTS_SNAPSHOT_UNAVAILABLE",
            "Permissions need verification",
            "No permissions snapshot for the supported artwork is available.",
            status="INCONCLUSIVE",
        )
    elif denied:
        lane(
            "RIGHTS",
            "PERMISSION_CONFLICT",
            "Recorded permission conflict",
            "The declared use conflicts with the matched artist's active recorded preferences."
            + (
                " A recorded license also exists; resolve the conflict before taking action."
                if authorized
                else ""
            ),
            tone="review" if authorized else "bad",
            status="INCONCLUSIVE" if authorized else "SUPPORTED",
            missing_facts=missing,
            permission_conflicts=permission_conflicts,
        )
    elif authorized:
        lane(
            "RIGHTS",
            "RECORDED_LICENSE_AUTHORIZES",
            "Recorded license authorizes use",
            "A recorded authorizing license covers the scan's declared use and scope.",
            authorizing_license_id=license_id,
            missing_facts=missing,
        )
    elif requires_license:
        lane(
            "RIGHTS",
            "REQUIRED_LICENSE_MISSING",
            "Required license not recorded",
            (
                "The active preferences require a license, but none authorizes this use in "
                "the saved records."
            ),
            tone="review",
            missing_facts=missing,
            limitations=["A license or applicable exception may exist outside CreatorProof."],
        )
    elif preference_active and preferences.get("preference") == "ALLOW":
        lane(
            "RIGHTS",
            "PREFERENCE_ALLOWS",
            "Artist preference allows use",
            (
                "The active artist preference allows the declared use; claimant authority "
                "and any license conditions still need verification."
            ),
            tone="review",
            missing_facts=missing,
        )
    else:
        lane(
            "RIGHTS",
            "AUTHORIZATION_UNVERIFIED",
            "Authorization unverified",
            (
                "Reuse is supported, but registration alone records no permission. No "
                "authorizing license was established for this use."
            ),
            status="INCONCLUSIVE",
            missing_facts=missing,
            limitations=["An absent recorded license is not proof that the use is unauthorized."],
        )

    policy = decision.get("policy_action")
    policy_outcomes = {
        "PASS_BY_POLICY": (
            "Pass under recorded policy",
            "The deterministic policy permits continuation for the declared scope.",
            "good",
        ),
        "REVIEW": (
            "Human review required",
            "The recorded policy requires review before publication or enforcement.",
            "review",
        ),
        "BLOCK": (
            "Blocked by recorded policy",
            "The recorded organizational policy blocks this declared use.",
            "bad",
        ),
    }
    if policy in policy_outcomes:
        label, explanation, tone = policy_outcomes[policy]
        lane("POLICY", policy, label, explanation, tone=tone)
    else:
        lane(
            "POLICY",
            "POLICY_NOT_RUN",
            "Policy decision unavailable",
            "No completed publication-policy decision was recorded.",
            status="NOT_RUN",
        )
    lane(
        "SOURCE_COVERAGE",
        "CHECKED_SCOPE_COMPLETE" if complete else "CHECKED_SCOPE_INCOMPLETE",
        "Checked sources complete" if complete else "Source coverage incomplete",
        "The requested registered corpus was checked; this is not a search of the entire web."
        if complete
        else (
            "Some requested sources were not fully checked. A negative result cannot "
            "clear those gaps."
        ),
        status="SUPPORTED" if complete else "INCONCLUSIVE",
        coverage_status=scope.get("coverage_status"),
    )
    commitment = any(
        row.get("signal_type") == "PACKET_COMMITMENT" and row.get("status") == "SUPPORTED"
        for row in signals
    )
    lane(
        "INTEGRITY",
        "COMMITMENT_RECORDED" if commitment else "COMMITMENT_NOT_RECORDED",
        "Evidence commitment recorded" if commitment else "Evidence commitment unavailable",
        (
            "A SHA-256 commitment identifies the saved evidence packet; it does not "
            "establish ownership."
        )
        if commitment
        else "No completed evidence-packet commitment was recorded.",
        status="SUPPORTED" if commitment else "NOT_RUN",
    )

    if failed:
        confirmed = False
        no_match = False
        for key in lanes:
            lane(
                key,
                "ASSESSMENT_FAILED",
                "Assessment did not complete",
                "The scan pipeline failed; no completed finding is established for this lane.",
                status="ERROR",
            )
        verdict, label, explanation = (
            "ASSESSMENT_FAILED",
            "Assessment did not complete",
            "Run a successful scan before deciding on misuse.",
        )
    elif confirmed and denied and not authorized:
        verdict, label, explanation = (
            "POTENTIAL_MISUSE_PERMISSION_CONFLICT",
            "Potential misuse: permission conflict",
            (
                "Artwork reuse is supported and the declared use conflicts with recorded "
                "artist preferences. Confirm the actual use, claimant authority, licenses "
                "and exceptions before enforcement."
            ),
        )
    elif confirmed and denied and authorized:
        verdict, label, explanation = (
            "CONFLICTING_PERMISSION_RECORDS",
            "Reuse confirmed; permissions conflict",
            (
                "A recorded license and artist preferences conflict. Resolve that conflict "
                "before deciding on misuse."
            ),
        )
    elif confirmed and authorized:
        verdict, label, explanation = (
            "RECORDED_AUTHORIZED_REUSE",
            "Reuse has a recorded authorizing license",
            (
                "Visual reuse is supported and a license covers the declared scope. Follow "
                "the recorded publication policy and verify the actual use stays within "
                "that scope."
            ),
        )
    elif confirmed and requires_license:
        verdict, label, explanation = (
            "POTENTIAL_MISUSE_REQUIRED_LICENSE",
            "Potential misuse: required license missing",
            (
                "Artwork reuse is supported and active preferences require a license. No "
                "authorizing license is recorded; verify any outside permission or "
                "exception before enforcement."
            ),
        )
    elif confirmed:
        verdict, label, explanation = (
            "REUSE_CONFIRMED_AUTHORIZATION_UNVERIFIED",
            "Reuse confirmed; authorization unverified",
            (
                "The recorded copy assessment supports artwork reuse. Permission facts do "
                "not establish whether that reuse is authorized, so misuse remains "
                "unverified."
            ),
        )
    elif no_match and complete:
        verdict, label, explanation = (
            "NO_MISUSE_ESTABLISHED_IN_CHECKED_SOURCES",
            "No misuse established in checked sources",
            (
                "No supported registered-artwork reuse was found. AI origin or style "
                "resemblance alone cannot establish misuse of an artist's artwork."
            ),
        )
    else:
        verdict, label, explanation = (
            "MISUSE_UNRESOLVED",
            "Misuse assessment needs more evidence",
            (
                "A validated artwork match or sufficient source coverage is missing. Review"
                " the unresolved checks before taking action."
            ),
        )
    from app.services.evidence_ratings import attach_ratings

    return attach_ratings(
        packet,
        {
            "version": ASSESSMENT_VERSION,
            "basis": "SAVED_MODEL_RESULTS_AND_RECORDED_PERMISSION_FACTS",
            "new_inference_performed": False,
            "lanes": lanes,
            "overall": {
                "verdict": verdict,
                "label": label,
                "explanation": explanation,
                "tone": "bad"
                if verdict.startswith("POTENTIAL_MISUSE")
                else "good"
                if verdict == "RECORDED_AUTHORIZED_REUSE"
                else "review"
                if confirmed or not (no_match and complete)
                else "neutral",
                "human_review_required": confirmed or not (no_match and complete),
                "legal_conclusion": None,
                "supported_findings": [
                    row["label"] for row in lanes.values() if row["status"] == "SUPPORTED"
                ],
                "unresolved_findings": [
                    row["label"]
                    for row in lanes.values()
                    if row["status"] in {"INCONCLUSIVE", "ERROR", "NOT_RUN", "PROVIDER_UNAVAILABLE"}
                ],
                "next_steps": [
                    "Review the supported image comparison.",
                    (
                        "Verify the actual published use, claimant authority, permissions and "
                        "any applicable exceptions."
                    ),
                    "Approve or dismiss the case before sending a notice.",
                ]
                if confirmed
                else [
                    "Review source coverage and any unresolved detector checks.",
                    "Obtain a validated artwork match before alleging misuse.",
                ],
            },
        },
    )
