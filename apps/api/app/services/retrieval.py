from dataclasses import dataclass, replace
from datetime import UTC, datetime

from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.enums import (
    CapabilityExecutionState,
    CopyRetrievalRequirement,
    CoverageReasonCode,
    CoverageStatus,
)
from app.models import Work
from app.providers.fingerprints import phash_distance
from app.services.ai_index import reference_embedding


@dataclass(frozen=True, slots=True)
class RetrievedWork:
    work: Work
    exact_sha256: bool
    phash_distance: int
    ai_similarity: float | None = None
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


@dataclass(frozen=True, slots=True)
class CatalogEntryCoverage:
    work_id: str
    sha256: str
    phash: str
    learned_embedding_state: str
    learned_embedding_reason: str | None


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
) -> tuple[list[RetrievedWork], int, RetrievalRuntime]:
    works = list(
        db.scalars(
            select(Work).where(
                Work.tenant_id == tenant_id,
                Work.catalog_id == catalog_id,
            )
        )
    )

    provider = container.ai_retrieval
    query_embedding = None
    fallback_reason = provider.unavailable_reason
    query_execution_state = CapabilityExecutionState.UNAVAILABLE
    if provider.available:
        try:
            query_embedding = provider.embed(candidate_image)
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
        distance = phash_distance(candidate_phash, work.phash)
        ai_similarity: float | None = None
        learned_embedding_state = (
            CapabilityExecutionState.UNAVAILABLE
            if query_execution_state == CapabilityExecutionState.UNAVAILABLE
            else CapabilityExecutionState.FAILED
            if query_execution_state == CapabilityExecutionState.FAILED
            else CapabilityExecutionState.READY
        )
        learned_embedding_reason = fallback_reason
        if query_embedding is not None:
            try:
                stored_embedding = reference_embedding(container, work.storage_key)
                if stored_embedding is not None:
                    ai_similarity = provider.similarity(query_embedding, stored_embedding)
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
                sha256=work.sha256,
                phash=work.phash,
                learned_embedding_state=str(learned_embedding_state),
                learned_embedding_reason=learned_embedding_reason,
            )
        )

        phash_similarity = max(0.0, 1.0 - distance / 64.0)
        retrieval_score = ai_similarity if ai_similarity is not None else phash_similarity
        ranked.append(
            RetrievedWork(
                work=work,
                exact_sha256=work.sha256 == candidate_sha256,
                phash_distance=distance,
                ai_similarity=ai_similarity,
                retrieval_score=round(float(retrieval_score), 6),
                retrieval_provider=provider.name if ai_similarity is not None else "phash-fallback",
            )
        )

    ai_active = query_embedding is not None and ai_similarity_count > 0
    if query_embedding is not None and works and not ai_active and fallback_reason is None:
        fallback_reason = "NO_REFERENCE_AI_EMBEDDINGS_AVAILABLE"

    def rank_key(item: RetrievedWork):
        if item.exact_sha256:
            return (0, 0.0, 0, item.work.id)
        if item.ai_similarity is not None:
            return (1, -item.ai_similarity, item.phash_distance, item.work.id)
        return (2, 0.0, item.phash_distance, item.work.id)

    ranked.sort(key=rank_key)
    ranked = [replace(item, retrieval_rank=index + 1) for index, item in enumerate(ranked)]
    runtime = RetrievalRuntime(
        provider=provider.name if ai_active else "phash-fallback",
        ai_active=ai_active,
        fallback_reason=fallback_reason if not ai_active else None,
        requested_provider=provider.name,
        query_execution_state=str(query_execution_state),
        ai_reference_count=ai_similarity_count,
        reference_failures=tuple(reference_failures),
        catalog_entries=tuple(catalog_entries),
        candidate_limit=top_k,
        model_identity=str(getattr(provider, "model_identity", provider.name)),
        preprocessing_identity=str(
            getattr(provider, "preprocessing_identity", "PROVIDER_DEFINED_PREPROCESSING")
        ),
        whole_image_query_count=1,
        regional_query_count=0,
    )
    return ranked[:top_k], len(works), runtime


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
        and set(failed_ids) <= candidate_work_id_set
    )
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
    if verification_failures:
        reason_codes.append(CoverageReasonCode.CANDIDATE_VERIFICATION_FAILURE)
    if len(verified_ids) < len(candidate_work_ids) and not verification_failures:
        reason_codes.append(CoverageReasonCode.CANDIDATE_VERIFICATION_PARTIAL)

    if not coverage_manifest_consistent:
        coverage_status = CoverageStatus.FAILED
    elif total_count == 0:
        coverage_status = CoverageStatus.EMPTY_SCOPE
    elif candidate_work_ids and not verified_ids and verification_failures:
        coverage_status = CoverageStatus.FAILED
    elif requirement == CopyRetrievalRequirement.LEARNED_REQUIRED and not learned_complete:
        coverage_status = CoverageStatus.DEGRADED
    elif verification_failures or len(verified_ids) < len(candidate_work_ids):
        coverage_status = CoverageStatus.PARTIAL
    elif truncated:
        coverage_status = CoverageStatus.TRUNCATED
    else:
        coverage_status = CoverageStatus.COMPLETE

    catalog_manifest = [
        {
            "work_id": entry.work_id,
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
        "verification_failures": verification_failures,
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
        "failed_candidate_count": len(failed_ids),
        "exact_hash_reference_count": total_count,
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
                "execution_state": str(CapabilityExecutionState.EXECUTED),
                "references_checked": total_count,
            },
            "phash_retrieval": {
                "required": True,
                "execution_state": str(CapabilityExecutionState.EXECUTED),
                "references_checked": total_count,
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
                    if verification_failures
                    else CapabilityExecutionState.EXECUTED
                ),
                "candidates_nominated": len(candidate_work_ids),
                "candidates_verified": len(verified_ids),
            },
        },
    }
