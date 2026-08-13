import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from datetime import UTC

from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.enums import (
    CapabilityExecutionState,
    ClaimState,
    CoverageStatus,
    MatchStatus,
    OriginPolicyMode,
    PolicyAction,
    RightsPath,
)
from app.models import Scan, Work
from app.services.copy_fusion import fuse_copy_evidence
from app.services.images import decode_image
from app.services.policy_trace import build_policy_trace
from app.services.retrieval import RetrievedWork, corpus_snapshot, retrieve_candidates
from app.services.runtime_telemetry import (
    current_telemetry,
    increment_counter,
    record_duration,
    record_observation,
)
from app.services.style_analysis import analyze_style
from app.services.synthetic_analysis import analyze_synthetic_origin


@dataclass(frozen=True, slots=True)
class CandidateEvidence:
    work_id: str
    title: str
    retrieval_rank: int
    retrieval_provider: str
    retrieval_score: float
    ai_similarity: float | None
    exact_sha256: bool
    phash_distance: int
    phash_similarity: float
    geometry: dict
    aligned_perceptual: dict
    fusion: dict
    visualization: dict
    copy_evidence_score: float
    prototype_evidence_score: float
    verification_state: str
    ai_regional_similarity: float | None = None
    retrieval_view: str = "whole_image"
    verification_rank: int = 0


def canonical_packet_bytes(payload: dict) -> bytes:
    """Legacy Evidence Packet v1 canonical bytes (distinct from statement JCS)."""
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


def canonical_hash(payload: dict) -> str:
    return hashlib.sha256(canonical_packet_bytes(payload)).hexdigest()


def _visualization(item: RetrievedWork, raw_geometry: dict) -> dict:
    """Build display-only evidence without changing match or policy semantics."""
    query_size = list(raw_geometry.get("query_size") or [0, 0])
    reference_size = list(raw_geometry.get("reference_size") or [0, 0])
    regions = list(raw_geometry.get("regions") or [])
    homography = raw_geometry.get("homography_query_to_reference")

    if item.exact_sha256:
        regions.insert(
            0,
            {
                "id": "region-exact-001",
                "kind": "EXACT_BINARY_MATCH",
                "label": "Byte-identical image",
                "query_polygon": [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]],
                "reference_polygon": [
                    [0.0, 0.0],
                    [1.0, 0.0],
                    [1.0, 1.0],
                    [0.0, 1.0],
                ],
                "supporting_inliers": raw_geometry.get("inliers", 0),
                "query_coverage": 1.0,
                "reprojection_error_px": raw_geometry.get("reprojection_error"),
            },
        )
        if homography is None and query_size == reference_size:
            homography = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]

    return {
        "schema": "creatorproof.visual_evidence.v1",
        "coordinate_space": "NORMALIZED_IMAGE_0_1",
        "query_size": query_size,
        "reference_size": reference_size,
        "correspondences": list(raw_geometry.get("correspondences") or []),
        "regions": regions,
        "homography_query_to_reference": homography,
        "display_notes": [
            "Annotations explain detector output; they are not a legal conclusion.",
            "Descriptor distance and geometric metrics are raw evidence, not probabilities.",
            "Aligned perceptual metrics are computed only after geometry passes robust gates.",
            "Verified support patches are envelopes around locally consistent matches; they are "
            "not semantic segmentation masks or claims that every enclosed pixel is shared.",
        ],
    }


def _decision(top: CandidateEvidence | None, scope: dict) -> MatchStatus:
    if top is not None and bool(top.fusion.get("match_supported")):
        return MatchStatus.MATCH_FOUND
    if top is not None and bool(top.fusion.get("review_supported")):
        return MatchStatus.INCONCLUSIVE
    if (
        bool(scope.get("complete_for_declared_catalog"))
        and scope.get("coverage_status") == CoverageStatus.COMPLETE
    ):
        return MatchStatus.NO_MATCH_IN_CHECKED_SOURCES
    return MatchStatus.SCOPE_INCOMPLETE


def _verification_sort_key(item: CandidateEvidence) -> tuple:
    """Pairwise verification re-ranks retrieved candidates without hiding retrieval rank."""
    fusion = item.fusion
    tier = (
        3
        if item.exact_sha256
        else 2
        if fusion.get("match_supported")
        else 1
        if fusion.get("review_supported")
        else 0
    )
    return (-tier, -float(fusion.get("evidence_index") or 0.0), item.retrieval_rank, item.work_id)


def _policy(
    match_status: MatchStatus,
    matched_work: Work | None,
    intended_use: str,
    *,
    coverage_status: CoverageStatus = CoverageStatus.COMPLETE,
    coverage_reason_codes: list[str] | None = None,
) -> tuple[PolicyAction, RightsPath, list[str]]:
    if match_status == MatchStatus.SCOPE_INCOMPLETE:
        return (
            PolicyAction.REVIEW,
            RightsPath.NO_LICENSE_INFO,
            [
                "SCOPE_INCOMPLETE_REQUIRES_REVIEW",
                *(coverage_reason_codes or []),
            ],
        )
    if match_status == MatchStatus.ERROR:
        return PolicyAction.REVIEW, RightsPath.NO_LICENSE_INFO, ["SCAN_ERROR_REQUIRES_REVIEW"]
    if match_status == MatchStatus.INCONCLUSIVE:
        return PolicyAction.REVIEW, RightsPath.NO_LICENSE_INFO, ["VISUAL_EVIDENCE_INCONCLUSIVE"]
    if match_status == MatchStatus.NO_MATCH_IN_CHECKED_SOURCES:
        return (
            PolicyAction.PASS_BY_POLICY,
            RightsPath.NO_LICENSE_INFO,
            ["NO_MATCH_IN_DECLARED_CATALOG", "PASS_IS_POLICY_NOT_COPYRIGHT_CLEARANCE"],
        )
    if coverage_status != CoverageStatus.COMPLETE:
        try:
            incomplete_rights_path = (
                RightsPath(matched_work.rights_path)
                if matched_work is not None
                else RightsPath.NO_LICENSE_INFO
            )
        except ValueError:
            incomplete_rights_path = RightsPath.NO_LICENSE_INFO
        return (
            PolicyAction.REVIEW,
            incomplete_rights_path,
            [
                "MATCH_FOUND_WITH_INCOMPLETE_SCOPE_REQUIRES_REVIEW",
                *(coverage_reason_codes or []),
            ],
        )
    if matched_work is None:
        return PolicyAction.REVIEW, RightsPath.NO_LICENSE_INFO, ["MATCH_WITHOUT_RIGHTS_RECORD"]

    try:
        rights_path = RightsPath(matched_work.rights_path)
    except ValueError:
        return PolicyAction.REVIEW, RightsPath.NO_LICENSE_INFO, ["MATCHED_RIGHTS_PATH_INVALID"]
    if rights_path == RightsPath.DISPUTED:
        return PolicyAction.REVIEW, rights_path, ["MATCHED_RIGHTS_RECORD_DISPUTED"]
    try:
        claim_state = ClaimState(matched_work.claim_state)
    except ValueError:
        return PolicyAction.REVIEW, rights_path, ["MATCHED_CLAIM_STATE_INVALID"]
    if claim_state != ClaimState.CORROBORATED:
        reason_by_state = {
            ClaimState.ASSERTED: "MATCHED_CLAIM_NOT_CORROBORATED",
            ClaimState.DISPUTED: "MATCHED_CLAIM_DISPUTED",
            ClaimState.SUPERSEDED: "MATCHED_CLAIM_SUPERSEDED",
            ClaimState.REVOKED: "MATCHED_CLAIM_REVOKED",
        }
        return PolicyAction.REVIEW, rights_path, [reason_by_state[claim_state]]
    if rights_path == RightsPath.EXISTING_LICENSE and intended_use in (
        matched_work.allowed_uses or []
    ):
        return PolicyAction.PASS_BY_POLICY, rights_path, ["MATCHED_USE_ALLOWED_BY_RIGHTS_RECORD"]
    if rights_path == RightsPath.LICENSE_AVAILABLE:
        return PolicyAction.REVIEW, rights_path, ["LICENSE_PATH_AVAILABLE_REVIEW_REQUIRED"]
    return PolicyAction.REVIEW, rights_path, ["MATCH_REQUIRES_RIGHTS_REVIEW"]


def _evidence_policy_baseline(
    match_status: MatchStatus,
    *,
    coverage_status: CoverageStatus = CoverageStatus.COMPLETE,
    coverage_reason_codes: list[str] | None = None,
) -> tuple[PolicyAction, RightsPath, list[str]]:
    """Return evidence-only safety semantics before stored rights are evaluated.

    This intentionally has no ``Work`` argument. A copy match can be authorized
    only later by the pinned PolicyVersion operating on persisted Claim/License
    facts; denormalized registration fields cannot influence a live decision.
    """
    if match_status == MatchStatus.SCOPE_INCOMPLETE:
        return (
            PolicyAction.REVIEW,
            RightsPath.NO_LICENSE_INFO,
            ["SCOPE_INCOMPLETE_REQUIRES_REVIEW", *(coverage_reason_codes or [])],
        )
    if match_status == MatchStatus.ERROR:
        return PolicyAction.REVIEW, RightsPath.NO_LICENSE_INFO, ["SCAN_ERROR_REQUIRES_REVIEW"]
    if match_status == MatchStatus.INCONCLUSIVE:
        return PolicyAction.REVIEW, RightsPath.NO_LICENSE_INFO, ["VISUAL_EVIDENCE_INCONCLUSIVE"]
    if match_status == MatchStatus.NO_MATCH_IN_CHECKED_SOURCES:
        return (
            PolicyAction.PASS_BY_POLICY,
            RightsPath.NO_LICENSE_INFO,
            ["NO_MATCH_IN_DECLARED_CATALOG", "PASS_IS_POLICY_NOT_COPYRIGHT_CLEARANCE"],
        )
    if coverage_status != CoverageStatus.COMPLETE:
        return (
            PolicyAction.REVIEW,
            RightsPath.NO_LICENSE_INFO,
            ["MATCH_FOUND_WITH_INCOMPLETE_SCOPE_REQUIRES_REVIEW", *(coverage_reason_codes or [])],
        )
    return (
        PolicyAction.REVIEW,
        RightsPath.NO_LICENSE_INFO,
        ["MATCH_REQUIRES_PERSISTED_RIGHTS_EVALUATION"],
    )


def _apply_style_policy_overlay(
    *,
    match_status: MatchStatus,
    policy_action: PolicyAction,
    reason_codes: list[str],
    style_analysis: dict,
    synthetic_analysis: dict | None = None,
    origin_policy_mode: OriginPolicyMode = OriginPolicyMode.INFORMATIONAL,
) -> tuple[PolicyAction, list[str], bool]:
    origin_policy_mode = OriginPolicyMode(origin_policy_mode)
    style_decision = style_analysis.get("decision") or {}
    review_recommended = bool(style_decision.get("review_recommended"))
    synthetic_analysis = synthetic_analysis or {}
    synthetic_classification = synthetic_analysis.get("classification")
    origin_requires_policy_review = bool(
        origin_policy_mode == OriginPolicyMode.REQUIRED
        and synthetic_classification
        and synthetic_classification != "NO_AI_ORIGIN_EVIDENCE_DETECTED"
    )
    style_tier = style_decision.get("evidence_tier")
    strong_ai_origin = synthetic_classification in {
        "AI_PROVENANCE_CONFIRMED",
        "AI_PROVENANCE_ASSERTED_UNTRUSTED_SIGNER",
        "LIKELY_AI_GENERATED",
        "AI_INDICATORS_CORROBORATED",
        "AI_ORIGIN_MARKER_FOUND",
    }
    joint_review = strong_ai_origin or (
        synthetic_classification == "AI_ORIGIN_REVIEW_CANDIDATE"
        and style_tier in {"HIGH", "VERY_HIGH"}
    )
    if origin_policy_mode != OriginPolicyMode.REQUIRED:
        if synthetic_classification:
            reason_codes = [
                *reason_codes,
                (
                    "AI_ORIGIN_CHECK_DISABLED_BY_POLICY"
                    if origin_policy_mode == OriginPolicyMode.DISABLED
                    else "AI_ORIGIN_INFORMATIONAL_ONLY"
                ),
            ]
        if review_recommended and match_status != MatchStatus.MATCH_FOUND:
            reason_codes = [
                *reason_codes,
                "STYLE_SIGNAL_NOT_AUTO_ESCALATED_WITHOUT_AI_ORIGIN_SUPPORT",
            ]
        return policy_action, list(dict.fromkeys(reason_codes)), review_recommended

    if review_recommended and joint_review and policy_action == PolicyAction.PASS_BY_POLICY:
        return (
            PolicyAction.REVIEW,
            [
                *reason_codes,
                "AI_ORIGIN_AND_STYLE_RESEMBLANCE_REVIEW_RECOMMENDED",
                "STYLE_REVIEW_IS_NOT_COPY_OR_INFRINGEMENT_FINDING",
            ],
            True,
        )
    if origin_requires_policy_review and policy_action == PolicyAction.PASS_BY_POLICY:
        return (
            PolicyAction.REVIEW,
            [
                *reason_codes,
                "AI_ORIGIN_RESULT_REQUIRES_PRODUCT_REVIEW",
                "AI_ORIGIN_REVIEW_IS_NOT_INFRINGEMENT_FINDING",
            ],
            review_recommended,
        )
    if review_recommended and not joint_review and match_status != MatchStatus.MATCH_FOUND:
        reason_codes = [
            *reason_codes,
            "STYLE_SIGNAL_NOT_AUTO_ESCALATED_WITHOUT_AI_ORIGIN_SUPPORT",
        ]
    return policy_action, list(dict.fromkeys(reason_codes)), review_recommended


def _joint_risk_summary(
    *,
    match_status: MatchStatus,
    policy_action: PolicyAction = PolicyAction.REVIEW,
    style_analysis: dict,
    synthetic_analysis: dict,
    origin_policy_mode: OriginPolicyMode = OriginPolicyMode.REQUIRED,
    coverage_status: str = CoverageStatus.COMPLETE,
) -> dict:
    origin_policy_mode = OriginPolicyMode(origin_policy_mode)
    style = style_analysis.get("decision") or {}
    style_tier = style.get("evidence_tier")
    origin = synthetic_analysis.get("classification")
    ai_supported = origin in {
        "AI_PROVENANCE_CONFIRMED",
        "LIKELY_AI_GENERATED",
        "AI_INDICATORS_CORROBORATED",
    }
    origin_review = bool(synthetic_analysis.get("review_recommended"))
    style_supported = style_tier in {"HIGH", "VERY_HIGH"}
    if match_status == MatchStatus.SCOPE_INCOMPLETE:
        classification = "SOURCE_SCOPE_INCOMPLETE"
        headline = "The declared source scope was not completely checked"
        case_action = "REVIEW_SCOPE"
        action = "Resolve the missing or truncated checks, then run the scan again."
    elif match_status == MatchStatus.MATCH_FOUND and ai_supported:
        classification = "AI_ASSISTED_COPY_EVIDENCE"
        headline = "AI indicators and a protected-work match were found"
        case_action = "REVIEW_RIGHTS_AND_ORIGIN"
        action = "Review the matched work and AI evidence before this asset is used."
    elif match_status == MatchStatus.MATCH_FOUND and origin_review:
        classification = "COPY_EVIDENCE_ORIGIN_REVIEW"
        headline = "Protected-work match found; AI origin needs review"
        case_action = "REVIEW_RIGHTS_AND_ORIGIN"
        action = "Review the match first, then check the uncertain AI evidence."
    elif match_status != MatchStatus.MATCH_FOUND and ai_supported and style_supported:
        classification = "AI_STYLE_RESEMBLANCE_REVIEW"
        headline = "AI indicators and creator-profile resemblance were found"
        case_action = "REVIEW_STYLE_AND_ORIGIN"
        action = "Review the creator profile and AI evidence; this is not a same-work match."
    elif match_status != MatchStatus.MATCH_FOUND and ai_supported:
        classification = "AI_INDICATORS_WITHOUT_RIGHTS_MATCH"
        headline = "AI indicators found; no stored-work match"
        case_action = "REVIEW_ORIGIN"
        action = "Review the AI evidence. No protected-work match was found in this catalog."
    elif match_status == MatchStatus.MATCH_FOUND:
        classification = "COPY_EVIDENCE_ORIGIN_UNRESOLVED"
        headline = "Protected-work match found; AI origin unresolved"
        case_action = "REVIEW_COPY_RIGHTS"
        action = "Review the matched work and its rights record before using this asset."
    elif origin_review and style_supported:
        classification = "ORIGIN_AND_STYLE_REVIEW"
        headline = "AI origin and creator-profile resemblance need review"
        case_action = "REVIEW_STYLE_AND_ORIGIN"
        action = "Review both signals; no same-work match was established."
    elif origin_review:
        classification = "AI_ORIGIN_REVIEW_WITHOUT_RIGHTS_MATCH"
        headline = "AI origin needs review; no stored-work match"
        case_action = "REVIEW_ORIGIN"
        action = "Do not treat the missing catalog match as proof that the image is human-made."
    elif style_supported:
        classification = "STYLE_RESEMBLANCE_ORIGIN_UNRESOLVED"
        headline = "Creator-profile resemblance found; AI origin unresolved"
        case_action = "REVIEW_STYLE"
        action = "Review the creator profile; style resemblance is not proof of copying."
    elif origin == "NO_AI_ORIGIN_EVIDENCE_DETECTED":
        classification = "NO_STRONG_AI_SIGNAL_OR_RIGHTS_MATCH"
        headline = "No strong AI indicators; no stored-work match"
        case_action = "RECORD_AND_CONTINUE"
        action = (
            "Preserve the evidence and apply company policy; this is not proof of human origin."
        )
    elif origin == "AI_ORIGIN_CHECK_DISABLED":
        classification = "AI_CHECK_DISABLED_WITHOUT_RIGHTS_MATCH"
        headline = "No stored-work match; AI-origin checks were disabled"
        case_action = "RECORD_AND_CONTINUE"
        action = "Apply the recorded policy without making an AI-origin inference."
    elif origin == "SYNTHETIC_ORIGIN_ANALYSIS_UNAVAILABLE":
        classification = "AI_CHECK_UNAVAILABLE_WITHOUT_RIGHTS_MATCH"
        headline = "AI check unavailable; no stored-work match"
        case_action = "ACTIVATE_AI_CHECKS"
        action = "Activate the AI checks and scan again before relying on the origin result."
    else:
        classification = "ORIGIN_UNKNOWN_WITHOUT_RIGHTS_MATCH"
        headline = "AI origin is uncertain; no stored-work match"
        case_action = "REVIEW_ORIGIN"
        action = (
            "Keep this case in review because the AI checks could not reach a dependable result."
        )
    if policy_action == PolicyAction.PASS_BY_POLICY and case_action != "RECORD_AND_CONTINUE":
        case_action = "RECORD_AND_CONTINUE"
        action = (
            "The AI-origin result is informational under this policy. Preserve it without "
            "changing the recorded policy action."
        )
    return {
        "classification": classification,
        "headline": headline,
        "case_action": case_action,
        "recommended_action": action,
        "ai_origin_supported": ai_supported,
        "ai_origin_review": origin_review,
        "style_supported": style_supported,
        "copy_supported": match_status == MatchStatus.MATCH_FOUND,
        "coverage_status": coverage_status,
        "origin_policy_mode": str(origin_policy_mode),
        "semantics": "PRODUCT_TRIAGE_NOT_LEGAL_INFRINGEMENT_DETERMINATION",
    }


def _disabled_origin_lane(container) -> tuple[dict, dict]:
    visible_marker = {
        "provider": container.visible_markers.name,
        "available": False,
        "checked": False,
        "classification": "VISIBLE_MARKER_CHECK_DISABLED",
        "supports_ai_origin_review": False,
        "marker_strength": None,
        "markers": [],
        "reason_codes": ["AI_ORIGIN_CHECK_DISABLED_BY_POLICY"],
        "limitations": ["No visible-label inference was made because this lane was disabled."],
    }
    synthetic_analysis = {
        "schema": "creatorproof.synthetic_origin.v4",
        "classification": "AI_ORIGIN_CHECK_DISABLED",
        "evidence_tier": "DISABLED",
        "review_recommended": False,
        "fused_detector_score": None,
        "visible_marker_signal": visible_marker,
        "scorecard": {
            "schema": "creatorproof.origin_scorecard.v1",
            "signal_score": 0,
            "signal_label": "Not evaluated",
            "evidence_quality_score": 0,
            "evidence_quality_label": "Not evaluated",
            "score_semantics": "NO_AI_ORIGIN_INFERENCE_PERFORMED",
            "plain_explanation": "AI-origin analysis was disabled by the recorded policy mode.",
            "factors": [],
        },
        "presentation": {
            "state": "CHECK_DISABLED",
            "tone": "quiet",
            "headline": "AI-origin checks were disabled",
            "summary": "CreatorProof made no AI-origin inference for this scan.",
            "action": "Apply the recorded policy without treating this as human-origin evidence.",
            "show_domain_score": False,
            "domain_score": None,
            "facts": [],
        },
        "reason_codes": ["AI_ORIGIN_CHECK_DISABLED_BY_POLICY"],
        "limitations": ["A disabled check is not evidence of human or AI origin."],
    }
    return visible_marker, synthetic_analysis


def _failed_origin_analysis(container, visible_marker: dict, exc: Exception) -> dict:
    marker_supported = bool(visible_marker.get("supports_ai_origin_review"))
    return {
        "schema": "creatorproof.synthetic_origin.v4",
        "classification": (
            "AI_ORIGIN_MARKER_FOUND"
            if marker_supported
            else "SYNTHETIC_ORIGIN_ANALYSIS_UNAVAILABLE"
        ),
        "evidence_tier": "REVIEW" if marker_supported else "UNAVAILABLE",
        "review_recommended": marker_supported,
        "fused_detector_score": None,
        "visible_marker_signal": visible_marker,
        "scorecard": {
            "schema": "creatorproof.origin_scorecard.v1",
            "signal_score": round(100 * float(visible_marker.get("marker_strength") or 0.0)),
            "signal_label": "AI signal found" if marker_supported else "AI checks unavailable",
            "evidence_quality_score": 0,
            "evidence_quality_label": "Low",
            "score_semantics": "SIGNAL_STRENGTH_AND_EVIDENCE_QUALITY_NOT_AI_PROBABILITY",
            "plain_explanation": (
                "The model check failed. Any visible label remains review evidence, not proof."
            ),
            "factors": [],
        },
        "presentation": {
            "state": "AI_INDICATORS_NEED_REVIEW" if marker_supported else "CHECK_UNAVAILABLE",
            "tone": "review" if marker_supported else "unavailable",
            "headline": (
                "A visible AI label was found"
                if marker_supported
                else "AI-origin checks are not active"
            ),
            "summary": (
                "The visible label remains review evidence, but the model analysis failed."
                if marker_supported
                else "The origin analysis failed without changing copy evidence."
            ),
            "action": (
                "Inspect the label and rerun the model checks before relying on origin."
                if marker_supported
                else "Inspect the provider error and rerun before relying on this lane."
            ),
            "show_domain_score": False,
            "domain_score": None,
            "facts": [],
        },
        "reason_codes": [f"SYNTHETIC_ANALYSIS_FAILED:{type(exc).__name__}"],
        "limitations": ["Synthetic-origin failure does not alter copy evidence."],
    }


def _analyze_origin_lane(
    container,
    query_image: Image.Image,
    provenance,
    *,
    candidate_raw: bytes | None = None,
    candidate_filename: str | None = None,
    policy_mode: OriginPolicyMode | str | None = None,
) -> tuple[dict, dict]:
    settings = container.settings
    mode = OriginPolicyMode(policy_mode or settings.synthetic_policy_mode)
    if mode == OriginPolicyMode.DISABLED:
        visible_marker, synthetic_analysis = _disabled_origin_lane(container)
        return visible_marker, {
            **synthetic_analysis,
            "policy_mode": str(mode),
            "execution_state": str(CapabilityExecutionState.SKIPPED_BY_POLICY),
        }

    try:
        visible_marker = asdict(container.visible_markers.inspect(query_image))
    except Exception as exc:
        visible_marker = {
            "provider": container.visible_markers.name,
            "available": False,
            "checked": False,
            "classification": "VISIBLE_MARKER_ANALYSIS_FAILED",
            "supports_ai_origin_review": False,
            "marker_strength": None,
            "markers": [],
            "reason_codes": [f"VISIBLE_MARKER_ANALYSIS_FAILED:{type(exc).__name__}"],
            "limitations": ["A failed visible-label check is not a negative result."],
        }
    try:
        synthetic_analysis = analyze_synthetic_origin(
            image=query_image,
            detector_router=container.synthetic_detection,
            provenance=provenance,
            settings=settings,
            visible_marker=visible_marker,
            source_media=candidate_raw,
            source_filename=candidate_filename,
        )
        execution_state = CapabilityExecutionState.EXECUTED
    except Exception as exc:
        synthetic_analysis = _failed_origin_analysis(container, visible_marker, exc)
        execution_state = CapabilityExecutionState.FAILED
    return visible_marker, {
        **synthetic_analysis,
        "policy_mode": str(mode),
        "execution_state": str(execution_state),
    }


def build_evidence_packet(
    container,
    db: Session,
    scan: Scan,
    candidate_raw: bytes,
    *,
    progress: Callable[[str, str, int], None] | None = None,
    defer_proof: bool = False,
) -> dict:
    pipeline_started = time.perf_counter()

    def report(stage: str, label: str, percent: int) -> None:
        if progress is not None:
            progress(stage, label, percent)

    settings = container.settings
    from app.models import ScanInputBinding

    input_binding = db.scalar(select(ScanInputBinding).where(ScanInputBinding.scan_id == scan.id))
    origin_policy_mode = OriginPolicyMode(
        (
            (input_binding.requested_capabilities or {}).get("origin_policy_mode")
            if input_binding is not None
            else None
        )
        or settings.synthetic_policy_mode
    )
    report("PREPARING_IMAGE", "Preparing the image", 5)
    stage_started = time.perf_counter()
    query_image = decode_image(
        candidate_raw,
        max_bytes=settings.max_upload_bytes,
        max_pixels=settings.max_image_pixels,
    )
    record_duration("image_decode", (time.perf_counter() - stage_started) * 1000)
    candidate_path = container.storage.root / scan.candidate_storage_key
    report("CHECKING_SOURCE", "Checking source information", 12)
    stage_started = time.perf_counter()
    provenance = container.provenance.inspect(candidate_path)
    record_duration("provenance", (time.perf_counter() - stage_started) * 1000)
    report("CHECKING_VISIBLE_LABELS", "Looking for visible AI labels", 20)
    report("CHECKING_AI_SIGNALS", "Checking AI-use signals", 32)
    stage_started = time.perf_counter()
    visible_marker, synthetic_analysis = _analyze_origin_lane(
        container,
        query_image,
        provenance,
        candidate_raw=candidate_raw,
        candidate_filename="candidate.bin",
        policy_mode=origin_policy_mode,
    )
    record_duration("origin_analysis", (time.perf_counter() - stage_started) * 1000)
    report("SEARCHING_CATALOG", "Searching registered works", 54)
    stage_started = time.perf_counter()
    ranked, total_count, retrieval_runtime = retrieve_candidates(
        db,
        container=container,
        candidate_image=query_image,
        tenant_id=scan.tenant_id,
        catalog_id=scan.catalog_id,
        candidate_sha256=scan.candidate_sha256,
        candidate_phash=scan.candidate_phash,
        top_k=settings.retrieval_top_k,
        exhaustive_max_entries=settings.copy_exhaustive_verification_max_entries,
    )
    record_duration("copy_retrieval", (time.perf_counter() - stage_started) * 1000)
    report("CHECKING_CREATOR_PROFILE", "Checking the creator profile", 66)
    stage_started = time.perf_counter()
    try:
        style_analysis = analyze_style(
            container,
            db,
            query_image=query_image,
            tenant_id=scan.tenant_id,
            catalog_id=scan.catalog_id,
            top_k=settings.style_top_k,
        )
    except Exception as exc:
        # The style lane is independent from copy verification. A style-provider failure is
        # recorded rather than converting an otherwise valid rights scan into a pipeline error.
        style_analysis = {
            "schema": "creatorproof.style_evidence.v2",
            "provider": container.style_retrieval.name,
            "learned_provider_active": container.style_retrieval.learned,
            "calibration_state": "UNAVAILABLE",
            "error_code": f"STYLE_ANALYSIS_FAILED:{type(exc).__name__}",
            "top_profiles": [],
            "diagnostics": None,
            "decision": {
                "review_recommended": False,
                "classification": "STYLE_ANALYSIS_UNAVAILABLE",
                "evidence_tier": "UNAVAILABLE",
                "reason_codes": [f"STYLE_ANALYSIS_FAILED:{type(exc).__name__}"],
            },
            "limitations": [
                "Style analysis failed independently; copy/derivative evidence remains valid."
            ],
        }
    style_analysis = {
        **style_analysis,
        "customer_facing_lane": "CREATOR_PROFILE_RESEMBLANCE",
    }
    record_duration("style_analysis", (time.perf_counter() - stage_started) * 1000)

    evidence: list[CandidateEvidence] = []
    work_by_id: dict[str, Work] = {}
    verified_work_ids: list[str] = []
    verification_failures: list[dict] = []
    report("VERIFYING_CLOSEST_MATCHES", "Comparing the closest registered works", 74)
    verification_started = time.perf_counter()
    for item_index, item in enumerate(ranked):
        work_by_id[item.work.id] = item.work
        try:
            asset_version = item.asset_version
            if asset_version is None:
                raise ValueError("REFERENCE_ASSET_VERSION_MISSING")
            reference_raw = container.storage.read(asset_version.storage_key)
            observed_sha256 = hashlib.sha256(reference_raw).hexdigest()
            if observed_sha256 != asset_version.sha256:
                raise ValueError("REFERENCE_ASSET_SHA256_MISMATCH")
            if len(reference_raw) != asset_version.byte_size:
                raise ValueError("REFERENCE_ASSET_BYTE_SIZE_MISMATCH")
            with Image.open(__import__("io").BytesIO(reference_raw)) as opened:
                reference_image = opened.convert("RGB")
                reference_image.load()
            raw_geometry = asdict(container.geometry.verify(query_image, reference_image))
            alignment = (
                raw_geometry.get("homography_query_to_reference")
                if raw_geometry.get("validated")
                else None
            )
            aligned_perceptual = asdict(
                container.aligned_perceptual.verify(
                    query_image,
                    reference_image,
                    alignment,
                    raw_geometry.get("regions") if alignment is not None else None,
                )
            )
            visualization = _visualization(item, raw_geometry)
            geometry = {
                key: value
                for key, value in raw_geometry.items()
                if key
                not in {
                    "query_size",
                    "reference_size",
                    "correspondences",
                    "regions",
                    "homography_query_to_reference",
                }
            }
            fusion = asdict(
                fuse_copy_evidence(
                    exact_sha256=item.exact_sha256,
                    ai_similarity=item.ai_similarity,
                    phash_similarity=max(0.0, 1.0 - item.phash_distance / 64.0),
                    geometry=geometry,
                    aligned_perceptual=aligned_perceptual,
                    settings=settings,
                )
            )
            score = float(fusion["evidence_index"])
            evidence.append(
                CandidateEvidence(
                    work_id=item.work.id,
                    title=item.work.title,
                    retrieval_rank=item.retrieval_rank,
                    retrieval_provider=item.retrieval_provider,
                    retrieval_score=item.retrieval_score,
                    ai_similarity=(
                        round(item.ai_similarity, 6) if item.ai_similarity is not None else None
                    ),
                    ai_regional_similarity=(
                        round(item.ai_regional_similarity, 6)
                        if item.ai_regional_similarity is not None
                        else None
                    ),
                    retrieval_view=item.retrieval_view,
                    exact_sha256=item.exact_sha256,
                    phash_distance=item.phash_distance,
                    phash_similarity=round(max(0.0, 1.0 - item.phash_distance / 64.0), 6),
                    geometry=geometry,
                    aligned_perceptual=aligned_perceptual,
                    fusion=fusion,
                    visualization=visualization,
                    copy_evidence_score=score,
                    # Deprecated v0.4 compatibility alias. Kept for older API clients.
                    prototype_evidence_score=score,
                    verification_state=str(fusion["classification"]),
                )
            )
            verified_work_ids.append(item.work.id)
        except Exception as exc:
            verification_failures.append(
                {
                    "work_id": item.work.id,
                    "retrieval_rank": item.retrieval_rank,
                    "error_code": f"CANDIDATE_VERIFICATION_FAILED:{type(exc).__name__}",
                }
            )
        report(
            "VERIFYING_CLOSEST_MATCHES",
            "Comparing the closest registered works",
            74 + round(14 * (item_index + 1) / max(1, len(ranked))),
        )

    record_duration(
        "copy_candidate_verification",
        (time.perf_counter() - verification_started) * 1000,
    )
    increment_counter("copy_candidates_nominated", len(ranked))
    increment_counter("copy_candidates_verified", len(verified_work_ids))
    increment_counter("copy_candidate_verification_failures", len(verification_failures))

    snapshot = corpus_snapshot(
        ranked,
        total_count=total_count,
        tenant_id=scan.tenant_id,
        catalog_id=scan.catalog_id,
        retrieval_runtime=retrieval_runtime,
        verified_work_ids=verified_work_ids,
        verification_failures=verification_failures,
        retrieval_requirement=settings.copy_retrieval_requirement,
    )

    # Global retrieval nominates candidates; pairwise verification owns final evidence order.
    # The original retrieval_rank remains in every row so the re-ranking is fully auditable.
    evidence.sort(key=_verification_sort_key)
    evidence = [replace(item, verification_rank=index + 1) for index, item in enumerate(evidence)]
    top = evidence[0] if evidence else None
    match_status = _decision(top, snapshot)
    matched_work = (
        work_by_id.get(top.work_id) if top and match_status == MatchStatus.MATCH_FOUND else None
    )
    baseline_action, baseline_rights_path, baseline_reason_codes = _evidence_policy_baseline(
        match_status,
        coverage_status=CoverageStatus(snapshot["coverage_status"]),
        coverage_reason_codes=snapshot.get("coverage_reason_codes") or [],
    )
    style_decision = style_analysis.get("decision") or {}
    style_review_recommended = bool(style_decision.get("review_recommended"))

    # The exact immutable policy selected when the scan was accepted owns this
    # decision. Missing/deleted policy state fails closed rather than silently
    # falling back to a newer version or to the legacy Work projection.
    from app.services.policy_store import collect_rights_facts, evaluate_policy

    policy_version = (
        container.policies.get_by_id(
            db,
            tenant_id=scan.tenant_id,
            policy_version_id=scan.policy_version_id,
        )
        if scan.policy_version_id
        else None
    )
    rights_facts = collect_rights_facts(
        db,
        tenant_id=scan.tenant_id,
        work_id=matched_work.id if matched_work is not None else None,
        intended_use=scan.intended_use,
    )
    if policy_version is None:
        policy_evaluation = {
            "policy_action": str(PolicyAction.REVIEW),
            "baseline_policy_action": str(baseline_action),
            "rights_path": str(rights_facts.get("derived_rights_path", baseline_rights_path)),
            "matched_rules": ["pinned_policy_version_must_exist"],
            "missing_facts": ["PINNED_POLICY_VERSION_NOT_FOUND"],
            "reason_codes": sorted(
                set([*baseline_reason_codes, "PINNED_POLICY_VERSION_NOT_FOUND"])
            ),
            "authorizing_license_id": None,
            "license_reason_codes": rights_facts.get("license_reason_codes") or [],
            "inputs": {},
            "notes": ["A missing pinned policy fails closed and requires review."],
        }
        policy_identity = "MISSING_PINNED_POLICY_VERSION"
    else:
        policy_evaluation = evaluate_policy(
            rules=policy_version.rules,
            baseline_action=baseline_action,
            baseline_reason_codes=baseline_reason_codes,
            match_status=match_status,
            coverage_status=CoverageStatus(snapshot["coverage_status"]),
            rights_path=baseline_rights_path,
            rights_facts=rights_facts,
            ai_origin_classification=synthetic_analysis.get("classification"),
            creator_profile_tier=style_decision.get("evidence_tier"),
            origin_policy_mode=str(origin_policy_mode),
            style_review_recommended=style_review_recommended,
        )
        policy_identity = policy_version.id

    policy_action = PolicyAction(policy_evaluation["policy_action"])
    rights_path = RightsPath(policy_evaluation["rights_path"])
    reason_codes = list(policy_evaluation["reason_codes"])
    policy_inputs = {
        "match_status": str(match_status),
        "coverage_status": snapshot.get("coverage_status"),
        "origin_policy_mode": str(origin_policy_mode),
        "intended_use": scan.intended_use,
        "matched_work_id": matched_work.id if matched_work is not None else None,
        "evidence_baseline": {
            "policy_action": str(baseline_action),
            "rights_path": str(baseline_rights_path),
            "reason_codes": baseline_reason_codes,
        },
        "rights_facts": rights_facts,
        # Compatibility shape retained for v1 consumers. These values are a
        # projection of the authoritative Claim/License snapshot, never Work.
        "matched_work": (
            {
                "work_id": matched_work.id,
                "claim_state": (
                    (rights_facts.get("claims") or [{}])[0].get("state")
                    if rights_facts.get("claims")
                    else None
                ),
                "rights_path": rights_facts.get("derived_rights_path"),
                "allowed_uses": sorted(
                    {
                        use
                        for license_fact in rights_facts.get("licenses") or []
                        for use in license_fact.get("permitted_uses") or []
                    }
                ),
                "source": "PERSISTED_CLAIM_AND_LICENSE_ROWS",
            }
            if matched_work is not None
            else None
        ),
        "policy": (
            {
                "id": policy_version.id,
                "policy_key": policy_version.policy_key,
                "version": policy_version.version,
                "digest_sha256": policy_version.digest_sha256,
            }
            if policy_version is not None
            else {"id": scan.policy_version_id, "state": "NOT_FOUND"}
        ),
    }
    policy_trace = build_policy_trace(
        policy_version=policy_identity,
        inputs=policy_inputs,
        outputs={
            "policy_action": str(policy_action),
            "rights_path": str(rights_path),
            "style_review_recommended": style_review_recommended,
            "authorizing_license_id": policy_evaluation.get("authorizing_license_id"),
        },
        matched_rule_codes=list(policy_evaluation.get("matched_rules") or []),
        missing_facts=list(policy_evaluation.get("missing_facts") or []),
    )
    for item in evidence:
        record_observation("copy_retrieval_score", item.retrieval_score)
        record_observation("copy_evidence_index", item.copy_evidence_score)
        record_observation("copy_ai_whole_similarity", item.ai_similarity)
        record_observation("copy_ai_regional_similarity", item.ai_regional_similarity)
    record_observation(
        "origin_fused_detector_score",
        synthetic_analysis.get("fused_detector_score"),
    )
    style_profiles = style_analysis.get("top_profiles") or []
    if style_profiles:
        record_observation("style_top_readout_score", style_profiles[0].get("readout_score"))
    record_duration(
        "evidence_pipeline_precommit",
        (time.perf_counter() - pipeline_started) * 1000,
    )
    telemetry = current_telemetry()
    runtime_telemetry = (
        telemetry.snapshot()
        if telemetry is not None
        else {
            "schema": "creatorproof.runtime_telemetry.v1",
            "state": "NOT_CAPTURED",
            "semantics": "OPERATIONAL_DIAGNOSTICS_NOT_ACCURACY_METRICS",
        }
    )
    packet = {
        "schema": "creatorproof.evidence_packet.v1",
        "packet_id": f"pkt_{scan.id}",
        "scan_id": scan.id,
        "created_at": scan.created_at.astimezone(UTC).isoformat(),
        "candidate_commitment": {
            "sha256": scan.candidate_sha256,
            "request_digest": scan.request_digest,
        },
        "scope": snapshot,
        "model_bundle": {
            **container.model_bundle.packet_record(
                runtime={
                    "copy_retrieval": container.ai_retrieval.status(),
                    "style": container.style_retrieval.status(),
                    "synthetic_origin": container.synthetic_detection.status(),
                    "visible_marker": container.visible_markers.status(),
                    "provenance": container.provenance.status(),
                }
            ),
            "fingerprint_provider": container.fingerprints.name,
            "retrieval_provider": retrieval_runtime.provider,
            "ai_retrieval_active": retrieval_runtime.ai_active,
            "ai_fallback_reason": retrieval_runtime.fallback_reason,
            "geometric_verifier": container.geometry.name,
            "aligned_perceptual_verifier": container.aligned_perceptual.name,
            "style_provider": style_analysis.get("provider"),
            "learned_style_active": style_analysis.get("learned_provider_active", False),
            "style_calibration": style_analysis.get("calibration_state"),
            "style_readout": (style_analysis.get("readout") or {}).get("method"),
            "style_fusion": "catalog-relative-empirical-support-style-fusion-v2",
            "synthetic_origin_provider": container.synthetic_detection.name,
            "synthetic_origin_detectors": [
                row.get("provider") for row in synthetic_analysis.get("members") or []
            ],
            "synthetic_origin_fusion": (
                "sightengine-primary-original-media-local-fallback-fusion-v4"
            ),
            "synthetic_origin_policy_mode": str(origin_policy_mode),
            "visible_marker_provider": container.visible_markers.name,
            "visible_marker_classification": visible_marker.get("classification"),
            "fusion": "corroborated-copy-evidence-fusion-v3-UNCALIBRATED",
            "runtime_validation": {
                "declared_state_verified": container.model_bundle_runtime[
                    "runtime_requirement_met_for_declared_state"
                ],
                "runtime_artifact_failures": container.model_bundle_runtime[
                    "runtime_artifact_failures"
                ],
                "terms_failures": container.model_bundle_runtime["terms_failures"],
                "application_revision_matches": container.model_bundle_runtime[
                    "application_revision"
                ]["matches"],
                "runtime_lock_matches": container.model_bundle_runtime["runtime_lock"]["matches"],
                "runtime_environment_matches": container.model_bundle_runtime[
                    "runtime_environment"
                ]["matches"],
                "demo_ready": container.model_bundle_runtime["demo_ready"],
            },
            "promotion_state": (
                container.model_bundle.qualification_state
                if container.model_bundle_runtime["runtime_requirement_met_for_declared_state"]
                else "DECLARED_STATE_REQUIREMENTS_NOT_MET"
            ),
        },
        "provenance": {
            "provider": provenance.provider,
            "status": provenance.status,
            "reason_codes": provenance.reason_codes,
            "manifest_summary": provenance.manifest_summary,
            "trust_details": provenance.trust_details,
        },
        "synthetic_origin": synthetic_analysis,
        "matches": [asdict(item) for item in evidence[:3]],
        "style_analysis": style_analysis,
        "runtime_telemetry": runtime_telemetry,
        "decision": {
            "match_status": match_status,
            "policy_action": policy_action,
            "rights_path": rights_path,
            "reason_codes": reason_codes,
            "intended_use": scan.intended_use,
            "policy_version": policy_identity,
            "policy_version_id": policy_version.id if policy_version is not None else None,
            "policy_key": policy_version.policy_key if policy_version is not None else None,
            "policy_version_number": policy_version.version if policy_version is not None else None,
            "policy_digest_sha256": (
                policy_version.digest_sha256 if policy_version is not None else None
            ),
            "policy_inputs": policy_inputs,
            "policy_trace": policy_trace,
            "policy_evaluation": policy_evaluation,
            "rights_facts_snapshot_digest_sha256": rights_facts.get("snapshot_digest_sha256"),
            "authorizing_license_id": policy_evaluation.get("authorizing_license_id"),
            "style_review_recommended": style_review_recommended,
            "style_evidence_tier": style_decision.get("evidence_tier"),
            "style_classification": style_decision.get("classification"),
            "synthetic_origin_classification": synthetic_analysis.get("classification"),
            "synthetic_origin_policy_mode": str(origin_policy_mode),
            "coverage_status": snapshot.get("coverage_status"),
            "joint_risk": _joint_risk_summary(
                match_status=match_status,
                policy_action=policy_action,
                style_analysis=style_analysis,
                synthetic_analysis=synthetic_analysis,
                origin_policy_mode=origin_policy_mode,
                coverage_status=str(snapshot.get("coverage_status")),
            ),
        },
        "proof": {
            "anchor_status": "PENDING",
            "provider": container.proof_anchor.name,
        },
        "limitations": [
            "Result is source-scoped and is not a legal infringement determination.",
            "Nearest registered candidate is a retrieval result, not proof of copying.",
            "Copy-fusion thresholds are prototype operating points; project-specific ROC/FPR "
            "calibration is required before production use.",
            "Unvalidated geometry emits no correspondence or region annotations.",
            "The copy evidence index is an auditable ranking score, not a probability of copying "
            "or infringement.",
            "C2PA is checked only when the official c2patool runtime is available; absence "
            "of a manifest never establishes human origin.",
            "SSCD is used only when its local TorchScript model and PyTorch runtime are available; "
            "the Evidence Packet explicitly reports fallback otherwise.",
            "The demo catalog uses exhaustive retrieval rather than a production ANN index.",
            "Creator-profile resemblance is an independent experimental lane; it cannot by "
            "itself "
            "establish copying, authorship, model training provenance, or infringement.",
            "A learned high-style result may route a no-copy case to human review without changing "
            "NO_MATCH_IN_CHECKED_SOURCES into MATCH_FOUND.",
            "AI-origin scores are open-world evidence, not proof of human or AI authorship.",
            "Creator-profile resemblance is advisory and cannot automatically block use.",
            "A local Merkle receipt is not blockchain; only an EAS receipt with a mined "
            "hash is represented as a public-chain anchor.",
        ],
    }
    packet_without_proof = {key: value for key, value in packet.items() if key != "proof"}
    packet_hash = canonical_hash(packet_without_proof)
    report("CREATING_RECEIPT", "Creating the evidence receipt", 94)
    packet["proof"] = {
        "anchor_status": "PENDING" if defer_proof else "NOT_REQUESTED",
        "provider": container.proof_anchor.name,
        "packet_hash_sha256": packet_hash,
        "packet_commitment_sha256": packet_hash,
        "commitment_scope": "CANONICAL_EVIDENCE_PACKET_EXCLUDING_PROOF_OBJECT",
        "receipt": None,
    }
    if not defer_proof:
        blockchain = getattr(container, "blockchain", None)
        proof = (
            blockchain.anchor_packet(
                packet_hash=packet_hash,
                scan_id=scan.id,
                tenant_id=scan.tenant_id,
            )
            if blockchain is not None
            else container.proof_anchor.anchor(packet_hash)
        )
        packet["proof"].update(
            {
                "anchor_status": proof.status,
                "provider": proof.provider,
                "receipt": proof.receipt,
            }
        )
    scan.match_status = str(match_status)
    scan.policy_action = str(policy_action)
    scan.rights_path = str(rights_path)
    scan.reason_codes = reason_codes
    scan.top_match_work_id = matched_work.id if matched_work else None
    scan.anchor_status = str(packet["proof"]["anchor_status"])
    scan.evidence_packet = packet
    return packet


def process_scan(container, scan_id: str) -> None:
    """Run one scan.

    Execution is owned by the platform layer. This wrapper keeps the original
    entry point stable for the worker, the container wiring and existing tests
    while the durable stage ledger, leases, retries, statement signing and proof
    anchoring live in :mod:`app.services.scan_runner`.
    """
    from app.services.scan_runner import run_scan

    run_scan(container, scan_id)
