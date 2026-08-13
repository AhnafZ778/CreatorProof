import hashlib
from dataclasses import dataclass, replace
from datetime import UTC, datetime

import numpy as np
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.enums import (
    CapabilityExecutionState,
    CopyRetrievalRequirement,
    CoverageReasonCode,
    CoverageStatus,
)
from app.models import AssetVersion, Work
from app.providers.fingerprints import phash_distance
from app.services.ai_index import reference_embedding


@dataclass(frozen=True, slots=True)
class RetrievedWork:
    work: Work
    exact_sha256: bool
    phash_distance: int
    asset_version: AssetVersion | None = None
    ai_similarity: float | None = None
    ai_regional_similarity: float | None = None
    retrieval_view: str = "whole_image"
    retrieval_score: float = 0.0
    retrieval_provider: str = "phash"
    retrieval_rank: int = 0


@dataclass(frozen=True, slots=True)
class RetrievalRuntime:
    provider: str
    ai_active: bool
    fallback_reason: str | None
    requested_provider: str
    query_execution_state: str
    ai_reference_count: int
    reference_failures: tuple[tuple[str, str], ...]
    catalog_entries: tuple["CatalogEntryCoverage", ...]
    candidate_limit: int
    model_identity: str
    preprocessing_identity: str
    whole_image_query_count: int
    regional_query_count: int
    query_policy_identity: str = "WHOLE_IMAGE_ONLY_V1"


@dataclass(frozen=True, slots=True)
class CatalogEntryCoverage:
    work_id: str
    sha256: str
    phash: str
    learned_embedding_state: str
    learned_embedding_reason: str | None
    asset_version_id: str | None = None
    asset_version: int | None = None


def regional_query_views(
    image: Image.Image,
    *,
    enabled: bool,
    crop_fraction: float,
    minimum_short_side: int,
) -> list[tuple[str, Image.Image]]:
    """Create deterministic overlapping crops used only for candidate nomination."""

    rgb = image.convert("RGB")
    views: list[tuple[str, Image.Image]] = [("whole_image", rgb)]
    width, height = rgb.size
    if not enabled or min(width, height) < minimum_short_side:
        return views
    crop_width = min(width, max(64, round(width * crop_fraction)))
    crop_height = min(height, max(64, round(height * crop_fraction)))
    if crop_width == width and crop_height == height:
        return views
    max_left = width - crop_width
    max_top = height - crop_height
    positions = (
        ("region_center", max_left // 2, max_top // 2),
        ("region_top_left", 0, 0),
        ("region_top_right", max_left, 0),
        ("region_bottom_left", 0, max_top),
        ("region_bottom_right", max_left, max_top),
    )
    seen: set[tuple[int, int, int, int]] = set()
    for label, left, top in positions:
        box = (left, top, left + crop_width, top + crop_height)
        if box in seen:
            continue
        seen.add(box)
        views.append((label, rgb.crop(box)))
    return views


def bounded_candidate_limit(
    *,
    total_count: int,
    requested_top_k: int,
    exhaustive_max_entries: int,
) -> int:
    if total_count > 0 and exhaustive_max_entries > 0 and total_count <= exhaustive_max_entries:
        return total_count
    return min(max(requested_top_k, 0), total_count)


def retrieve_candidates(
    db: Session,
    *,
    container,
    candidate_image: Image.Image,
    tenant_id: str,
    catalog_id: str,
    candidate_sha256: str,
    candidate_phash: str,
    top_k: int,
    exhaustive_max_entries: int = 0,
) -> tuple[list[RetrievedWork], int, RetrievalRuntime]:
    works = list(
        db.scalars(
            select(Work).where(
                Work.tenant_id == tenant_id,
                Work.catalog_id == catalog_id,
            )
        )
    )
    work_ids = [work.id for work in works]
    asset_versions: dict[str, AssetVersion] = {}
    if work_ids:
        # AssetVersion is append-only. Work remains a compatibility/catalog row,
        # but no fingerprint or object key from that mutable projection is trusted
        # for retrieval.
        for version in db.scalars(
            select(AssetVersion)
            .where(
                AssetVersion.tenant_id == tenant_id,
                AssetVersion.work_id.in_(work_ids),
            )
            .order_by(AssetVersion.work_id, AssetVersion.version.desc())
        ):
            asset_versions.setdefault(version.work_id, version)

    provider = container.ai_retrieval
    query_embeddings: list[tuple[str, np.ndarray]] = []
    fallback_reason = provider.unavailable_reason
    query_execution_state = CapabilityExecutionState.UNAVAILABLE
    if provider.available:
        try:
            settings = container.settings
            views = regional_query_views(
                candidate_image,
                enabled=getattr(settings, "copy_regional_retrieval_enabled", True),
                crop_fraction=getattr(settings, "copy_regional_crop_fraction", 0.64),
                minimum_short_side=getattr(settings, "copy_regional_min_short_side", 192),
            )
            embed_many = getattr(provider, "embed_many", None)
            vectors = (
                embed_many([view for _label, view in views])
                if callable(embed_many)
                else [provider.embed(view) for _label, view in views]
            )
            if len(vectors) != len(views):
                raise RuntimeError("COPY_QUERY_EMBEDDING_COUNT_INVALID")
            query_embeddings = [
                (label, vector) for (label, _view), vector in zip(views, vectors, strict=True)
            ]
            fallback_reason = None
            query_execution_state = CapabilityExecutionState.EXECUTED
        except Exception as exc:
            fallback_reason = f"AI_QUERY_FAILED:{type(exc).__name__}"
            query_execution_state = CapabilityExecutionState.FAILED

    ranked: list[RetrievedWork] = []
    ai_similarity_count = 0
    reference_failures: list[tuple[str, str]] = []
    catalog_entries: list[CatalogEntryCoverage] = []
    for work in works:
        asset_version = asset_versions.get(work.id)
        if asset_version is None:
            reason = "REFERENCE_ASSET_VERSION_MISSING"
            reference_failures.append((work.id, reason))
            catalog_entries.append(
                CatalogEntryCoverage(
                    work_id=work.id,
                    asset_version_id=None,
                    asset_version=None,
                    sha256="",
                    phash="",
                    learned_embedding_state=str(CapabilityExecutionState.FAILED),
                    learned_embedding_reason=reason,
                )
            )
            continue

        # Verify the object before it can influence either baseline or learned
        # nomination. This deliberately favours integrity over trusting a stale
        # embedding cached under the expected digest.
        try:
            reference_raw = container.storage.read(asset_version.storage_key)
            observed_sha256 = hashlib.sha256(reference_raw).hexdigest()
            if observed_sha256 != asset_version.sha256:
                raise ValueError("REFERENCE_ASSET_SHA256_MISMATCH")
            if len(reference_raw) != asset_version.byte_size:
                raise ValueError("REFERENCE_ASSET_BYTE_SIZE_MISMATCH")
        except Exception as exc:
            reason = (
                str(exc)
                if str(exc).startswith("REFERENCE_ASSET_")
                else (f"REFERENCE_ASSET_READ_FAILED:{type(exc).__name__}")
            )
            reference_failures.append((work.id, reason))
            catalog_entries.append(
                CatalogEntryCoverage(
                    work_id=work.id,
                    asset_version_id=asset_version.id,
                    asset_version=asset_version.version,
                    sha256=asset_version.sha256,
                    phash=asset_version.phash,
                    learned_embedding_state=str(CapabilityExecutionState.FAILED),
                    learned_embedding_reason=reason,
                )
            )
            continue

        distance = phash_distance(candidate_phash, asset_version.phash)
        ai_similarity: float | None = None
        learned_embedding_state = (
            CapabilityExecutionState.UNAVAILABLE
            if query_execution_state == CapabilityExecutionState.UNAVAILABLE
            else CapabilityExecutionState.FAILED
            if query_execution_state == CapabilityExecutionState.FAILED
            else CapabilityExecutionState.READY
        )
        learned_embedding_reason = fallback_reason
        regional_similarity: float | None = None
        retrieval_view = "whole_image"
        if query_embeddings:
            try:
                stored_embedding = reference_embedding(
                    container,
                    asset_version.storage_key,
                    source_sha256=asset_version.sha256,
                )
                if stored_embedding is not None:
                    view_scores = [
                        (label, provider.similarity(vector, stored_embedding))
                        for label, vector in query_embeddings
                    ]
                    ai_similarity = float(view_scores[0][1])
                    regional_scores = view_scores[1:]
                    if regional_scores:
                        regional_label, regional_similarity = max(
                            regional_scores,
                            key=lambda item: (item[1], item[0]),
                        )
                        penalty = float(
                            getattr(
                                container.settings,
                                "copy_regional_similarity_penalty",
                                0.02,
                            )
                        )
                        if regional_similarity - penalty > ai_similarity:
                            retrieval_view = regional_label
                    ai_similarity_count += 1
                    learned_embedding_state = CapabilityExecutionState.EXECUTED
                    learned_embedding_reason = None
                else:
                    learned_embedding_state = CapabilityExecutionState.UNAVAILABLE
                    learned_embedding_reason = "REFERENCE_AI_EMBEDDING_UNAVAILABLE"
                    reference_failures.append((work.id, learned_embedding_reason))
            except Exception as exc:
                ai_similarity = None
                learned_embedding_state = CapabilityExecutionState.FAILED
                learned_embedding_reason = f"REFERENCE_AI_EMBEDDING_FAILED:{type(exc).__name__}"
                reference_failures.append((work.id, learned_embedding_reason))

        catalog_entries.append(
            CatalogEntryCoverage(
                work_id=work.id,
                asset_version_id=asset_version.id,
                asset_version=asset_version.version,
                sha256=asset_version.sha256,
                phash=asset_version.phash,
                learned_embedding_state=str(learned_embedding_state),
                learned_embedding_reason=learned_embedding_reason,
            )
        )

        phash_similarity = max(0.0, 1.0 - distance / 64.0)
        retrieval_score = ai_similarity if ai_similarity is not None else phash_similarity
        if regional_similarity is not None:
            retrieval_score = max(
                retrieval_score,
                regional_similarity
                - float(
                    getattr(
                        container.settings,
                        "copy_regional_similarity_penalty",
                        0.02,
                    )
                ),
            )
        ranked.append(
            RetrievedWork(
                work=work,
                asset_version=asset_version,
                exact_sha256=asset_version.sha256 == candidate_sha256,
                phash_distance=distance,
                ai_similarity=ai_similarity,
                ai_regional_similarity=regional_similarity,
                retrieval_score=round(float(retrieval_score), 6),
                retrieval_provider=provider.name if ai_similarity is not None else "phash-fallback",
                retrieval_view=retrieval_view,
            )
        )

    ai_active = bool(query_embeddings) and ai_similarity_count > 0
    if query_embeddings and works and not ai_active and fallback_reason is None:
        fallback_reason = "NO_REFERENCE_AI_EMBEDDINGS_AVAILABLE"

    def rank_key(item: RetrievedWork):
        if item.exact_sha256:
            return (0, 0.0, 0, item.work.id)
        if item.ai_similarity is not None:
            return (1, -item.retrieval_score, item.phash_distance, item.work.id)
        return (2, 0.0, item.phash_distance, item.work.id)

    ranked.sort(key=rank_key)
    ranked = [replace(item, retrieval_rank=index + 1) for index, item in enumerate(ranked)]
    candidate_limit = bounded_candidate_limit(
        total_count=len(works),
        requested_top_k=top_k,
        exhaustive_max_entries=exhaustive_max_entries,
    )
    runtime = RetrievalRuntime(
        provider=provider.name if ai_active else "phash-fallback",
        ai_active=ai_active,
        fallback_reason=fallback_reason if not ai_active else None,
        requested_provider=provider.name,
        query_execution_state=str(query_execution_state),
        ai_reference_count=ai_similarity_count,
        reference_failures=tuple(reference_failures),
        catalog_entries=tuple(catalog_entries),
        candidate_limit=candidate_limit,
        model_identity=str(getattr(provider, "model_identity", provider.name)),
        preprocessing_identity=str(
            getattr(provider, "preprocessing_identity", "PROVIDER_DEFINED_PREPROCESSING")
        ),
        whole_image_query_count=1,
        regional_query_count=max(0, len(query_embeddings) - 1),
        query_policy_identity=(
            "SSCD_WHOLE_PLUS_FIVE_OVERLAPPING_REGIONS_V1"
            if len(query_embeddings) > 1
            else "SSCD_WHOLE_IMAGE_ONLY_V1"
        ),
    )
    return ranked[:candidate_limit], len(works), runtime


def corpus_snapshot(
    works: list[RetrievedWork],
    *,
    total_count: int,
    tenant_id: str,
    catalog_id: str,
    retrieval_runtime: RetrievalRuntime,
    verified_work_ids: list[str],
    verification_failures: list[dict],
    retrieval_requirement: CopyRetrievalRequirement,
) -> dict:
    import hashlib
    import json

    requirement = CopyRetrievalRequirement(retrieval_requirement)
    candidate_work_ids = [item.work.id for item in works]
    verified_ids = sorted(set(verified_work_ids))
    failed_ids = sorted(
        {
            str(item.get("work_id"))
            for item in verification_failures
            if item.get("work_id") is not None
        }
    )
    manifest_work_ids = [entry.work_id for entry in retrieval_runtime.catalog_entries]
    manifest_work_id_set = set(manifest_work_ids)
    candidate_work_id_set = set(candidate_work_ids)
    coverage_manifest_consistent = bool(
        len(manifest_work_ids) == total_count
        and len(manifest_work_id_set) == len(manifest_work_ids)
        and candidate_work_id_set <= manifest_work_id_set
        and set(verified_ids) <= candidate_work_id_set
        and set(failed_ids) <= manifest_work_id_set
    )
    asset_integrity_failures = [
        {"work_id": work_id, "error_code": reason}
        for work_id, reason in retrieval_runtime.reference_failures
        if reason.startswith("REFERENCE_ASSET_")
    ]
    combined_verification_failures = [*asset_integrity_failures, *verification_failures]
    learned_complete = bool(
        retrieval_runtime.query_execution_state == CapabilityExecutionState.EXECUTED
        and retrieval_runtime.ai_reference_count == total_count
        and not retrieval_runtime.reference_failures
    )
    truncated = len(candidate_work_ids) < total_count
    reason_codes: list[CoverageReasonCode] = []
    if not coverage_manifest_consistent:
        reason_codes.append(CoverageReasonCode.COVERAGE_MANIFEST_INCONSISTENT)
    if total_count == 0:
        reason_codes.append(CoverageReasonCode.DECLARED_CATALOG_EMPTY)
    if requirement == CopyRetrievalRequirement.LEARNED_REQUIRED and not learned_complete:
        reason_codes.append(CoverageReasonCode.REQUIRED_LEARNED_RETRIEVAL_INCOMPLETE)
    if truncated:
        reason_codes.append(CoverageReasonCode.CANDIDATE_VERIFICATION_TRUNCATED)
    if combined_verification_failures:
        reason_codes.append(CoverageReasonCode.CANDIDATE_VERIFICATION_FAILURE)
    if len(verified_ids) < len(candidate_work_ids) and not verification_failures:
        reason_codes.append(CoverageReasonCode.CANDIDATE_VERIFICATION_PARTIAL)

    if not coverage_manifest_consistent or asset_integrity_failures:
        coverage_status = CoverageStatus.FAILED
    elif total_count == 0:
        coverage_status = CoverageStatus.EMPTY_SCOPE
    elif candidate_work_ids and not verified_ids and verification_failures:
        coverage_status = CoverageStatus.FAILED
    elif requirement == CopyRetrievalRequirement.LEARNED_REQUIRED and not learned_complete:
        coverage_status = CoverageStatus.DEGRADED
    elif combined_verification_failures or len(verified_ids) < len(candidate_work_ids):
        coverage_status = CoverageStatus.PARTIAL
    elif truncated:
        coverage_status = CoverageStatus.TRUNCATED
    else:
        coverage_status = CoverageStatus.COMPLETE

    catalog_manifest = [
        {
            "work_id": entry.work_id,
            "asset_version_id": entry.asset_version_id,
            "asset_version": entry.asset_version,
            "sha256": entry.sha256,
            "phash": entry.phash,
            "learned_embedding_state": entry.learned_embedding_state,
            "learned_embedding_reason": entry.learned_embedding_reason,
        }
        for entry in sorted(retrieval_runtime.catalog_entries, key=lambda item: item.work_id)
    ]
    catalog_version_material = {
        "tenant_id": tenant_id,
        "catalog_id": catalog_id,
        "eligible_entries": [
            {
                "work_id": entry["work_id"],
                "asset_version_id": entry["asset_version_id"],
                "asset_version": entry["asset_version"],
                "sha256": entry["sha256"],
                "phash": entry["phash"],
            }
            for entry in catalog_manifest
        ],
    }
    catalog_version_digest = hashlib.sha256(
        json.dumps(catalog_version_material, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    candidate_id_set = set(candidate_work_ids)
    omitted_work_ids = [
        entry["work_id"] for entry in catalog_manifest if entry["work_id"] not in candidate_id_set
    ]
    material = {
        "tenant_id": tenant_id,
        "catalog_id": catalog_id,
        "catalog_version": f"manifest_{catalog_version_digest[:20]}",
        "eligible_reference_count": total_count,
        "catalog_manifest": catalog_manifest,
        "candidate_work_ids": candidate_work_ids,
        "verified_work_ids": verified_ids,
        "omitted_work_ids": omitted_work_ids,
        "omitted_reference_reasons": [
            {"work_id": work_id, "reason_code": "CANDIDATE_LIMIT"} for work_id in omitted_work_ids
        ],
        "verification_failures": combined_verification_failures,
        "coverage_status": str(coverage_status),
        "coverage_reason_codes": [str(reason) for reason in reason_codes],
        "retrieval_requirement": str(requirement),
        "query_counts": {
            "whole_image": retrieval_runtime.whole_image_query_count,
            "regional": retrieval_runtime.regional_query_count,
        },
        "provider_identity": {
            "requested_retrieval_provider": retrieval_runtime.requested_provider,
            "executed_retrieval_provider": retrieval_runtime.provider,
            "model": retrieval_runtime.model_identity,
            "preprocessing": retrieval_runtime.preprocessing_identity,
            "query_policy": retrieval_runtime.query_policy_identity,
        },
    }
    digest = hashlib.sha256(
        json.dumps(material, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return {
        **material,
        "snapshot_id": f"local_{digest[:20]}",
        "snapshot_digest_sha256": digest,
        "created_at": datetime.now(UTC).isoformat(),
        # Compatibility field retained for v1 consumers. The typed status is authoritative.
        "complete_for_declared_catalog": coverage_status == CoverageStatus.COMPLETE,
        "reference_count": total_count,
        "searched_reference_count": total_count,
        "nominated_candidate_count": len(candidate_work_ids),
        "verified_candidate_count": len(verified_ids),
        "omitted_candidate_count": max(0, total_count - len(candidate_work_ids)),
        "failed_candidate_count": len(
            set(failed_ids) | {item["work_id"] for item in asset_integrity_failures}
        ),
        "exact_hash_reference_count": max(0, total_count - len(asset_integrity_failures)),
        "descriptor_coverage": {
            "provider": retrieval_runtime.requested_provider,
            "available_reference_count": retrieval_runtime.ai_reference_count,
            "missing_reference_count": max(0, total_count - retrieval_runtime.ai_reference_count),
        },
        "candidate_limit": retrieval_runtime.candidate_limit,
        "retrieval_provider": retrieval_runtime.provider,
        "requested_retrieval_provider": retrieval_runtime.requested_provider,
        "ai_retrieval_active": retrieval_runtime.ai_active,
        "ai_fallback_reason": retrieval_runtime.fallback_reason,
        "capabilities": {
            "exact_sha256": {
                "required": True,
                "execution_state": str(
                    CapabilityExecutionState.FAILED
                    if asset_integrity_failures
                    else CapabilityExecutionState.EXECUTED
                ),
                "references_checked": max(0, total_count - len(asset_integrity_failures)),
            },
            "phash_retrieval": {
                "required": True,
                "execution_state": str(
                    CapabilityExecutionState.FAILED
                    if asset_integrity_failures
                    else CapabilityExecutionState.EXECUTED
                ),
                "references_checked": max(0, total_count - len(asset_integrity_failures)),
            },
            "learned_retrieval": {
                "required": requirement == CopyRetrievalRequirement.LEARNED_REQUIRED,
                "execution_state": retrieval_runtime.query_execution_state,
                "references_checked": retrieval_runtime.ai_reference_count,
                "reference_failures": [
                    {"work_id": work_id, "reason": reason}
                    for work_id, reason in retrieval_runtime.reference_failures
                ],
            },
            "local_verification": {
                "required": True,
                "execution_state": str(
                    CapabilityExecutionState.FAILED
                    if combined_verification_failures
                    else CapabilityExecutionState.EXECUTED
                ),
                "candidates_nominated": len(candidate_work_ids),
                "candidates_verified": len(verified_ids),
            },
        },
    }
