from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import asdict
from io import BytesIO

import numpy as np
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Work
from app.providers.style_signature import explain_style_pair
from app.services.ai_index import reference_embedding
from app.services.style_fusion import fuse_style_evidence
from app.services.style_index import reference_style_embedding
from app.services.style_readout import (
    aggregated_discrimination_gaps,
    catalog_relative_empirical_support,
    corpus_profile_readout,
    normalize,
)


def _profile_key(work: Work) -> str:
    claimant = (work.claimant or "").strip().casefold()
    return f"creator:{claimant}" if claimant else f"singleton:{work.id}"


def _profile_id(key: str) -> str:
    return f"sty_{hashlib.sha256(key.encode()).hexdigest()[:16]}"


def _profile_strength(sample_count: int) -> str:
    if sample_count >= 3:
        return "MULTI_WORK_PROFILE"
    if sample_count == 2:
        return "LIMITED_PROFILE"
    return "SINGLE_WORK_WEAK"


def _read_reference(container, work: Work) -> Image.Image:
    with Image.open(BytesIO(container.storage.read(work.storage_key))) as opened:
        image = opened.convert("RGB")
        image.load()
    return image


def _content_control(
    container,
    query_image: Image.Image,
    works: list[Work],
) -> tuple[dict[str, float], str | None]:
    provider = container.ai_retrieval
    if not provider.available:
        return {}, provider.unavailable_reason or "SSCD_CONTENT_CONTROL_UNAVAILABLE"
    try:
        query_vector = normalize(provider.embed(query_image))
        scores: dict[str, float] = {}
        for work in works:
            vector = reference_embedding(container, work.storage_key)
            if vector is not None:
                scores[work.id] = provider.similarity(query_vector, vector)
        return scores, None if scores else "SSCD_CONTENT_CONTROL_EMPTY"
    except Exception as exc:
        return {}, f"SSCD_CONTENT_CONTROL_FAILED:{type(exc).__name__}"


def _rank_with_provider(
    container,
    provider,
    query_image: Image.Image,
    works: list[Work],
    *,
    query_vector: np.ndarray | None = None,
) -> tuple[list[dict], dict]:
    settings = container.settings
    query_vector = normalize(provider.embed(query_image) if query_vector is None else query_vector)
    vectors = {
        work.id: reference_style_embedding(container, provider, work.storage_key) for work in works
    }
    grouped: dict[str, list[Work]] = defaultdict(list)
    for work in works:
        grouped[_profile_key(work)].append(work)
    group_ids = {key: [member.id for member in members] for key, members in grouped.items()}

    readouts = corpus_profile_readout(
        query_vector,
        vectors,
        group_ids,
        csls_k=settings.style_csls_k,
    )
    gaps = aggregated_discrimination_gaps(vectors, group_ids)
    csls_active = bool(provider.learned and len(grouped) >= 2 and len(vectors) >= 3)
    content_scores, content_reason = _content_control(container, query_image, works)

    profiles: list[dict] = []
    for key, members in grouped.items():
        prototype = normalize(np.mean([vectors[member.id] for member in members], axis=0))
        prototype_similarity = provider.similarity(query_vector, prototype)
        member_scores = sorted(
            ((provider.similarity(query_vector, vectors[member.id]), member) for member in members),
            key=lambda pair: (-pair[0], pair[1].id),
        )
        exemplar_similarity, exemplar = member_scores[0]
        strongest_member_scores = [score for score, _ in member_scores[:3]]
        robust_member_similarity = float(np.median(strongest_member_scores))
        legacy_profile_similarity = (
            0.65 * float(prototype_similarity) + 0.35 * robust_member_similarity
        )
        pairwise_cohesion: float | None = None
        if len(members) >= 2:
            pairwise = [
                provider.similarity(vectors[left.id], vectors[right.id])
                for left_index, left in enumerate(members)
                for right in members[left_index + 1 :]
            ]
            pairwise_cohesion = float(np.median(pairwise)) if pairwise else None

        raw_pool_similarity = float(readouts[key]["raw_pool_similarity"])
        csls_score = readouts[key]["csls_score"]
        readout_score = (
            float(csls_score) if csls_active and csls_score is not None else raw_pool_similarity
        )
        gap = gaps[key]
        content_values = [
            content_scores[member.id] for member in members if member.id in content_scores
        ]
        content_similarity = float(np.mean(content_values)) if content_values else None
        worst_key = gap["worst_cross_profile_key"]
        worst_members = grouped.get(str(worst_key), []) if worst_key else []
        profiles.append(
            {
                "profile_id": _profile_id(key),
                "_profile_key": key,
                "creator": (members[0].claimant or "Unassigned creator").strip(),
                "sample_count": len(members),
                "profile_strength": _profile_strength(len(members)),
                "prototype_similarity": round(float(prototype_similarity), 6),
                "robust_member_similarity": round(robust_member_similarity, 6),
                # Compatibility field: intentionally retained, explicitly labelled legacy below.
                "profile_similarity": round(legacy_profile_similarity, 6),
                "raw_pool_similarity": round(raw_pool_similarity, 6),
                "csls_score": round(float(csls_score), 6) if csls_score is not None else None,
                "readout_score": round(readout_score, 6),
                "readout_method": "CSD_PLUS_CSLS" if csls_active else "RAW_POOL_COSINE",
                "raw_cosine_interpretable": (
                    bool(float(gap["discrimination_gap"]) > 0)
                    if gap["discrimination_gap"] is not None
                    else None
                ),
                "within_pool_median": (
                    round(float(gap["within_pool_median"]), 6)
                    if gap["within_pool_median"] is not None
                    else None
                ),
                "worst_cross_pool_median": (
                    round(float(gap["worst_cross_pool_median"]), 6)
                    if gap["worst_cross_pool_median"] is not None
                    else None
                ),
                "discrimination_gap": (
                    round(float(gap["discrimination_gap"]), 6)
                    if gap["discrimination_gap"] is not None
                    else None
                ),
                "worst_cross_creator": (
                    (worst_members[0].claimant or "Unassigned creator").strip()
                    if worst_members
                    else None
                ),
                "content_similarity": (
                    round(content_similarity, 6) if content_similarity is not None else None
                ),
                "style_content_gap": (
                    round(raw_pool_similarity - content_similarity, 6)
                    if content_similarity is not None
                    else None
                ),
                "within_profile_cohesion": (
                    round(pairwise_cohesion, 6) if pairwise_cohesion is not None else None
                ),
                "exemplar_work_id": exemplar.id,
                "exemplar_title": exemplar.title,
                "exemplar_similarity": round(float(exemplar_similarity), 6),
                "member_scores": [
                    {
                        "work_id": member.id,
                        "title": member.title,
                        "similarity": round(float(score), 6),
                        "content_similarity": (
                            round(float(content_scores[member.id]), 6)
                            if member.id in content_scores
                            else None
                        ),
                    }
                    for score, member in member_scores
                ],
            }
        )

    profiles.sort(key=lambda item: (-float(item["readout_score"]), item["profile_id"]))
    readout_scores = [float(item["readout_score"]) for item in profiles]
    raw_scores = np.asarray([item["raw_pool_similarity"] for item in profiles], dtype=np.float64)
    raw_mean = float(raw_scores.mean()) if len(raw_scores) else 0.0
    raw_std = float(raw_scores.std()) if len(raw_scores) >= 3 else 0.0
    for rank, item in enumerate(profiles, start=1):
        score = float(item["readout_score"])
        item["readout_rank"] = rank
        item["catalog_percentile"] = round(
            sum(other <= score for other in readout_scores) / len(readout_scores), 6
        )
        item["catalog_relative_z"] = (
            round((float(item["raw_pool_similarity"]) - raw_mean) / raw_std, 6)
            if raw_std > 1e-6
            else None
        )

    return profiles, {
        "method": "CSD_PLUS_CSLS" if csls_active else "RAW_POOL_COSINE",
        "csls_active": csls_active,
        "csls_k_requested": settings.style_csls_k,
        "reference_count": len(vectors),
        "profile_count": len(grouped),
        "content_control_provider": container.ai_retrieval.name,
        "content_control_active": bool(content_scores),
        "content_control_reason": content_reason,
    }


def _empty_analysis(status: dict) -> dict:
    return {
        "schema": "creatorproof.style_evidence.v2",
        "customer_facing_lane": "CREATOR_PROFILE_RESEMBLANCE",
        "provider": status["provider"],
        "learned_provider_active": status["learned"],
        "fallback_reason": status["reason"],
        "calibration_state": "NO_REFERENCE_CORPUS",
        "readout": {"method": "UNAVAILABLE", "csls_active": False},
        "top_profiles": [],
        "diagnostics": None,
        "decision": {
            "evidence_index": 0.0,
            "evidence_tier": "LOW",
            "classification": "NO_STYLE_REFERENCE_CORPUS",
            "review_recommended": False,
            "score_semantics": "NO_STYLE_EVIDENCE",
            "reason_codes": ["NO_REGISTERED_STYLE_REFERENCES"],
        },
        "limitations": ["No registered works exist in the declared catalog."],
    }


def analyze_style(
    container,
    db: Session,
    *,
    query_image: Image.Image,
    tenant_id: str,
    catalog_id: str,
    top_k: int = 5,
) -> dict:
    works = list(
        db.scalars(
            select(Work).where(
                Work.tenant_id == tenant_id,
                Work.catalog_id == catalog_id,
            )
        )
    )
    router = container.style_retrieval
    if not works:
        return _empty_analysis(router.status())

    try:
        query_vector = router.embed(query_image)
        provider = router.active
        profiles, readout = _rank_with_provider(
            container, provider, query_image, works, query_vector=query_vector
        )
    except Exception as exc:
        if router.learned:
            router.force_fallback(f"CSD_REFERENCE_RUNTIME_FALLBACK:{type(exc).__name__}")
            provider = router.active
            profiles, readout = _rank_with_provider(container, provider, query_image, works)
        else:
            raise

    status = router.status()
    top_margin = None
    if profiles and len(profiles) > 1:
        top_margin = round(
            float(profiles[0]["readout_score"]) - float(profiles[1]["readout_score"]), 6
        )
    profiles = profiles[:top_k]
    diagnostics = None
    fusion = None
    calibration = None
    if profiles:
        exemplar = next(work for work in works if work.id == profiles[0]["exemplar_work_id"])
        diagnostics = explain_style_pair(query_image, _read_reference(container, exemplar))
        top_profile = profiles[0]
        calibration = catalog_relative_empirical_support(
            float(top_profile["raw_pool_similarity"]),
            vectors={
                work.id: reference_style_embedding(container, provider, work.storage_key)
                for work in works
            },
            groups={
                key: [member.id for member in works if _profile_key(member) == key]
                for key in {_profile_key(work) for work in works}
            },
            target_group=str(top_profile["_profile_key"]),
            min_profile_works=container.settings.style_min_profile_works,
            min_profiles=container.settings.style_min_calibration_profiles,
            min_negatives=container.settings.style_min_calibration_negatives,
        )
        top_profile["calibration"] = {
            key: round(float(value), 6) if isinstance(value, float) else value
            for key, value in calibration.items()
        }
        fusion = fuse_style_evidence(
            learned_provider_active=status["learned"],
            raw_style_similarity=float(top_profile["raw_pool_similarity"]),
            factors=diagnostics.get("factors"),
            tile_map=diagnostics.get("tile_map"),
            content_similarity=top_profile.get("content_similarity"),
            sample_count=int(top_profile["sample_count"]),
            discrimination_gap=top_profile.get("discrimination_gap"),
            catalog_margin=top_margin,
            calibration=calibration,
            settings=container.settings,
        )
        diagnostics["summary"] = {
            "mechanics_similarity": fusion.mechanics_similarity,
            "bidirectional_tile_consistency": fusion.tile_consistency,
            "semantics": "TRANSPARENT_LOW_LEVEL_STYLE_DIAGNOSTICS_NOT_ATTRIBUTION",
        }

    if status["learned"] and calibration and calibration.get("ready"):
        calibration_state = "CATALOG_RELATIVE_EMPIRICAL_SUPPORT_READY"
    elif status["learned"] and readout["csls_active"]:
        calibration_state = "CORPUS_CORRECTED_INSUFFICIENT_EMPIRICAL_SUPPORT"
    elif status["learned"]:
        calibration_state = "LIMITED_CATALOG_RAW_COSINE_UNCALIBRATED"
    else:
        calibration_state = "DIAGNOSTIC_ONLY_NOT_ATTRIBUTION"

    limitations = [
        "Style retrieval is separate from copy/derivative detection and does not require "
        "shared content.",
        "Style resemblance is review evidence, not proof of copying, training-data use, "
        "authorship, or legal infringement.",
        "The style evidence index is a transparent uncalibrated ranking aid, not a probability.",
        "CSD+ CSLS corrects catalog hubness for ranking but does not turn raw cosine into a "
        "universal threshold.",
        "Creator/domain thresholds require held-out positives, difficult related-style "
        "negatives, and creator-disjoint evaluation.",
        "Singleton profiles support pairwise resemblance review only; reliable creator "
        "attribution needs multiple representative works.",
        "SSCD is used as a copy/content control, never as a style veto.",
        "Palette/tone/edge/texture diagnostics are low-level explanations, not semantic "
        "masks or latent-dimension explanations.",
    ]
    if status["learned"]:
        limitations.append(
            "The upstream CSD repository flags a discrepancy in its uploaded weights; "
            "benchmark the exact pinned checkpoint before promotion."
        )
    else:
        limitations.append(
            "The learned style provider is inactive; diagnostic fallback results cannot "
            "trigger creator-attribution policy review."
        )

    for profile in profiles:
        profile.pop("_profile_key", None)

    return {
        "schema": "creatorproof.style_evidence.v2",
        "customer_facing_lane": "CREATOR_PROFILE_RESEMBLANCE",
        "provider": status["provider"],
        "requested_provider": status["requested_provider"],
        "learned_provider_active": status["learned"],
        "fallback_reason": status["reason"],
        "calibration_state": calibration_state,
        "score_semantics": (
            "CSD_RAW_POOL_COSINE_PLUS_CATALOG_READOUT"
            if status["learned"]
            else "DIAGNOSTIC_STYLE_VECTOR_COSINE"
        ),
        "legacy_profile_method": "0.65*CENTROID_COSINE+0.35*MEDIAN_TOP3_MEMBER_COSINE",
        "profile_method": "MEAN_QUERY_TO_CREATOR_ANCHOR_COSINE_WITH_OPTIONAL_CSD_PLUS_CSLS_RANKING",
        "readout": readout,
        "top_vs_runner_up_margin": top_margin,
        "top_profiles": profiles,
        "diagnostics": diagnostics,
        "decision": asdict(fusion) if fusion is not None else None,
        "limitations": limitations,
    }
