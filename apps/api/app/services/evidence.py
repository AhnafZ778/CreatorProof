import hashlib
import json
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime

from PIL import Image
from sqlalchemy import update
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
from app.services.retrieval import RetrievedWork, corpus_snapshot, retrieve_candidates
from app.services.style_analysis import analyze_style
from app.services.synthetic_analysis import analyze_synthetic_origin

POLICY_VERSION = "creatorproof-demo-policy-v1"


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
    verification_rank: int = 0


def canonical_hash(payload: dict) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return hashlib.sha256(encoded).hexdigest()


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
        "schema": "creatorproof.synthetic_origin.v3",
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
        "schema": "creatorproof.synthetic_origin.v3",
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


def _analyze_origin_lane(container, query_image: Image.Image, provenance) -> tuple[dict, dict]:
    settings = container.settings
    mode = OriginPolicyMode(settings.synthetic_policy_mode)
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
    def report(stage: str, label: str, percent: int) -> None:
        if progress is not None:
            progress(stage, label, percent)

    settings = container.settings
    report("PREPARING_IMAGE", "Preparing the image", 5)
    query_image = decode_image(
        candidate_raw,
        max_bytes=settings.max_upload_bytes,
        max_pixels=settings.max_image_pixels,
    )
    candidate_path = container.storage.root / scan.candidate_storage_key
    report("CHECKING_SOURCE", "Checking source information", 12)
    provenance = container.provenance.inspect(candidate_path)
    report("CHECKING_VISIBLE_LABELS", "Looking for visible AI labels", 20)
    report("CHECKING_AI_SIGNALS", "Checking AI-use signals", 32)
    visible_marker, synthetic_analysis = _analyze_origin_lane(container, query_image, provenance)
    report("SEARCHING_CATALOG", "Searching registered works", 54)
    ranked, total_count, retrieval_runtime = retrieve_candidates(
        db,
        container=container,
        candidate_image=query_image,
        tenant_id=scan.tenant_id,
        catalog_id=scan.catalog_id,
        candidate_sha256=scan.candidate_sha256,
        candidate_phash=scan.candidate_phash,
        top_k=settings.retrieval_top_k,
    )
    report("CHECKING_CREATOR_PROFILE", "Checking the creator profile", 66)
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

    evidence: list[CandidateEvidence] = []
    work_by_id: dict[str, Work] = {}
    verified_work_ids: list[str] = []
    verification_failures: list[dict] = []
    report("VERIFYING_CLOSEST_MATCHES", "Comparing the closest registered works", 74)
    for item_index, item in enumerate(ranked):
        work_by_id[item.work.id] = item.work
        try:
            reference_raw = container.storage.read(item.work.storage_key)
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
                container.aligned_perceptual.verify(query_image, reference_image, alignment)
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
    policy_action, rights_path, reason_codes = _policy(
        match_status,
        matched_work,
        scan.intended_use,
        coverage_status=CoverageStatus(snapshot["coverage_status"]),
        coverage_reason_codes=snapshot.get("coverage_reason_codes") or [],
    )
    style_decision = style_analysis.get("decision") or {}
    # Style evidence cannot manufacture a copy match. It can, however, stop a source-scoped
    # PASS_BY_POLICY and route a high/review learned-style case to a human policy review.
    policy_action, reason_codes, style_review_recommended = _apply_style_policy_overlay(
        match_status=match_status,
        policy_action=policy_action,
        reason_codes=reason_codes,
        style_analysis=style_analysis,
        synthetic_analysis=synthetic_analysis,
        origin_policy_mode=settings.synthetic_policy_mode,
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
            "bundle_id": "creatorproof-multi-lane-evidence-v0.9",
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
            "synthetic_origin_fusion": "evidence-family-multicrop-visible-marker-fusion-v3",
            "synthetic_origin_policy_mode": str(settings.synthetic_policy_mode),
            "visible_marker_provider": container.visible_markers.name,
            "visible_marker_classification": visible_marker.get("classification"),
            "fusion": "corroborated-copy-evidence-fusion-v3-UNCALIBRATED",
            "promotion_state": "EXPERIMENTAL",
        },
        "provenance": {
            "provider": provenance.provider,
            "status": provenance.status,
            "reason_codes": provenance.reason_codes,
            "manifest_summary": provenance.manifest_summary,
        },
        "synthetic_origin": synthetic_analysis,
        "matches": [asdict(item) for item in evidence[:3]],
        "style_analysis": style_analysis,
        "decision": {
            "match_status": match_status,
            "policy_action": policy_action,
            "rights_path": rights_path,
            "reason_codes": reason_codes,
            "intended_use": scan.intended_use,
            "policy_version": POLICY_VERSION,
            "policy_inputs": {
                "match_status": str(match_status),
                "coverage_status": snapshot.get("coverage_status"),
                "origin_policy_mode": str(settings.synthetic_policy_mode),
                "intended_use": scan.intended_use,
                "matched_work": (
                    {
                        "work_id": matched_work.id,
                        "claim_state": str(matched_work.claim_state),
                        "rights_path": str(matched_work.rights_path),
                        "allowed_uses": list(matched_work.allowed_uses or []),
                    }
                    if matched_work is not None
                    else None
                ),
            },
            "style_review_recommended": style_review_recommended,
            "style_evidence_tier": style_decision.get("evidence_tier"),
            "style_classification": style_decision.get("classification"),
            "synthetic_origin_classification": synthetic_analysis.get("classification"),
            "synthetic_origin_policy_mode": str(settings.synthetic_policy_mode),
            "coverage_status": snapshot.get("coverage_status"),
            "joint_risk": _joint_risk_summary(
                match_status=match_status,
                policy_action=policy_action,
                style_analysis=style_analysis,
                synthetic_analysis=synthetic_analysis,
                origin_policy_mode=settings.synthetic_policy_mode,
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
        proof = container.proof_anchor.anchor(packet_hash)
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
    from app.domain.enums import MatchStatus, ScanState
    from app.models import Scan

    db = container.database.session_factory()
    scan: Scan | None = None
    claimed = False
    try:
        claim = db.execute(
            update(Scan)
            .where(Scan.id == scan_id, Scan.state == ScanState.QUEUED)
            .values(state=ScanState.PROCESSING, error_code=None)
        )
        db.commit()
        if claim.rowcount != 1:
            return
        claimed = True
        scan = db.get(Scan, scan_id)
        if scan is None:
            return

        progress_started_at = datetime.now(UTC).isoformat()

        def update_progress(stage: str, label: str, percent: int) -> None:
            scan.evidence_packet = {
                "schema": "creatorproof.scan_progress.v1",
                "progress": {
                    "stage": stage,
                    "label": label,
                    "percent": max(0, min(int(percent), 99)),
                    "started_at": progress_started_at,
                    "updated_at": datetime.now(UTC).isoformat(),
                    "poll_after_ms": 750,
                    "can_resume": True,
                },
            }
            scan.reason_codes = ["SCAN_IN_PROGRESS"]
            db.commit()

        update_progress("STARTING", "Starting the evidence checks", 2)
        if not scan.candidate_storage_key:
            raise RuntimeError("CANDIDATE_MISSING")
        raw = container.storage.read(scan.candidate_storage_key)
        defer_proof = container.settings.environment != "test"
        packet = build_evidence_packet(
            container,
            db,
            scan,
            raw,
            progress=update_progress,
            defer_proof=defer_proof,
        )
        scan.state = ScanState.COMPLETED
        scan.completed_at = datetime.now(UTC)
        db.commit()
        if defer_proof:
            try:
                packet_hash = str(packet["proof"]["packet_hash_sha256"])
                try:
                    proof = container.proof_anchor.anchor(packet_hash)
                    proof_status = proof.status
                    proof_provider = proof.provider
                    proof_receipt = proof.receipt
                except Exception as exc:
                    proof_status = "FAILED"
                    proof_provider = container.proof_anchor.name
                    proof_receipt = {"error_code": f"PROOF_ANCHOR_FAILED:{type(exc).__name__}"}
                packet = {
                    **packet,
                    "proof": {
                        **packet["proof"],
                        "anchor_status": proof_status,
                        "provider": proof_provider,
                        "receipt": proof_receipt,
                    },
                }
                scan.anchor_status = str(proof_status)
                scan.evidence_packet = packet
                db.commit()
            except Exception:
                # The core evidence result is already committed. A proof-provider or
                # proof-update failure must never turn that completed result into FAILED.
                db.rollback()
    except Exception as exc:
        db.rollback()
        if scan is None:
            scan = db.get(Scan, scan_id)
        if scan is not None:
            scan.state = ScanState.FAILED
            scan.match_status = MatchStatus.ERROR
            scan.policy_action = PolicyAction.REVIEW
            scan.error_code = type(exc).__name__
            scan.reason_codes = ["PIPELINE_ERROR"]
            scan.completed_at = datetime.now(UTC)
            db.commit()
        raise
    finally:
        if claimed and scan is not None and container.settings.candidate_retention_seconds == 0:
            container.storage.delete(scan.candidate_storage_key)
        db.close()
