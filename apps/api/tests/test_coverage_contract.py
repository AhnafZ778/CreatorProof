from types import SimpleNamespace

import pytest

from app.domain.enums import CopyRetrievalRequirement, CoverageStatus
from app.services.retrieval import (
    CatalogEntryCoverage,
    RetrievalRuntime,
    RetrievedWork,
    corpus_snapshot,
)


def _entry(work_id: str, state: str = "EXECUTED") -> CatalogEntryCoverage:
    return CatalogEntryCoverage(
        work_id=work_id,
        sha256=f"sha-{work_id}",
        phash=f"phash-{work_id}",
        learned_embedding_state=state,
        learned_embedding_reason=None if state == "EXECUTED" else "MODEL_UNAVAILABLE",
    )


def _runtime(
    entries: list[CatalogEntryCoverage],
    *,
    query_state: str = "EXECUTED",
    ai_reference_count: int | None = None,
    candidate_limit: int = 8,
) -> RetrievalRuntime:
    count = len(entries) if ai_reference_count is None else ai_reference_count
    return RetrievalRuntime(
        provider="sscd-disc-mixup-torchscript" if count else "phash-fallback",
        ai_active=count > 0,
        fallback_reason=None if count else "MODEL_UNAVAILABLE",
        requested_provider="sscd-disc-mixup-torchscript",
        query_execution_state=query_state,
        ai_reference_count=count,
        reference_failures=(),
        catalog_entries=tuple(entries),
        candidate_limit=candidate_limit,
        model_identity="test-model-v1",
        preprocessing_identity="test-preprocessing-v1",
        whole_image_query_count=1,
        regional_query_count=0,
    )


def _candidate(work_id: str) -> RetrievedWork:
    return RetrievedWork(
        work=SimpleNamespace(id=work_id),
        exact_sha256=False,
        phash_distance=12,
        retrieval_rank=1,
    )


def _snapshot(
    candidate_ids: list[str],
    *,
    entries: list[CatalogEntryCoverage],
    verified_ids: list[str],
    requirement: CopyRetrievalRequirement = CopyRetrievalRequirement.BASELINE_ALLOWED,
    query_state: str = "EXECUTED",
    ai_reference_count: int | None = None,
    verification_failures: list[dict] | None = None,
    candidate_limit: int = 8,
) -> dict:
    return corpus_snapshot(
        [_candidate(work_id) for work_id in candidate_ids],
        total_count=len(entries),
        tenant_id="tenant-test",
        catalog_id="catalog-test",
        retrieval_runtime=_runtime(
            entries,
            query_state=query_state,
            ai_reference_count=ai_reference_count,
            candidate_limit=candidate_limit,
        ),
        verified_work_ids=verified_ids,
        verification_failures=verification_failures or [],
        retrieval_requirement=requirement,
    )


@pytest.mark.parametrize(
    ("candidate_ids", "verified_ids", "entries", "failures", "expected"),
    [
        ([], [], [], [], CoverageStatus.EMPTY_SCOPE),
        (["one"], ["one"], [_entry("one")], [], CoverageStatus.COMPLETE),
        (
            ["one", "two"],
            ["one"],
            [_entry("one"), _entry("two")],
            [],
            CoverageStatus.PARTIAL,
        ),
        (
            ["one"],
            [],
            [_entry("one")],
            [{"work_id": "one", "error_code": "VERIFICATION_FAILED"}],
            CoverageStatus.FAILED,
        ),
    ],
)
def test_coverage_status_lattice(candidate_ids, verified_ids, entries, failures, expected):
    snapshot = _snapshot(
        candidate_ids,
        entries=entries,
        verified_ids=verified_ids,
        verification_failures=failures,
    )

    assert snapshot["coverage_status"] == expected
    assert snapshot["complete_for_declared_catalog"] is (expected == CoverageStatus.COMPLETE)


def test_candidate_limit_exposes_truncated_scope_and_omitted_references():
    entries = [_entry("one"), _entry("two")]
    snapshot = _snapshot(
        ["one"],
        entries=entries,
        verified_ids=["one"],
        candidate_limit=1,
    )

    assert snapshot["coverage_status"] == CoverageStatus.TRUNCATED
    assert snapshot["omitted_work_ids"] == ["two"]
    assert snapshot["omitted_reference_reasons"] == [
        {"work_id": "two", "reason_code": "CANDIDATE_LIMIT"}
    ]
    assert "CANDIDATE_VERIFICATION_TRUNCATED" in snapshot["coverage_reason_codes"]


def test_required_learned_retrieval_exposes_degraded_scope():
    snapshot = _snapshot(
        ["one"],
        entries=[_entry("one", "UNAVAILABLE")],
        verified_ids=["one"],
        requirement=CopyRetrievalRequirement.LEARNED_REQUIRED,
        query_state="UNAVAILABLE",
        ai_reference_count=0,
    )

    assert snapshot["coverage_status"] == CoverageStatus.DEGRADED
    assert snapshot["descriptor_coverage"]["missing_reference_count"] == 1
    assert "REQUIRED_LEARNED_RETRIEVAL_INCOMPLETE" in snapshot["coverage_reason_codes"]


def test_snapshot_digest_tracks_capability_state_but_catalog_version_tracks_membership():
    entries_ready = [_entry("one")]
    entries_unavailable = [_entry("one", "UNAVAILABLE")]
    ready = _snapshot(["one"], entries=entries_ready, verified_ids=["one"])
    unavailable = _snapshot(
        ["one"],
        entries=entries_unavailable,
        verified_ids=["one"],
        query_state="UNAVAILABLE",
        ai_reference_count=0,
    )

    assert ready["catalog_version"] == unavailable["catalog_version"]
    assert ready["snapshot_digest_sha256"] != unavailable["snapshot_digest_sha256"]
    assert ready["tenant_id"] == "tenant-test"
    assert ready["query_counts"] == {"whole_image": 1, "regional": 0}
    assert ready["provider_identity"]["model"] == "test-model-v1"


def test_inconsistent_manifest_fails_closed():
    snapshot = corpus_snapshot(
        [_candidate("one")],
        total_count=2,
        tenant_id="tenant-test",
        catalog_id="catalog-test",
        retrieval_runtime=_runtime([_entry("one")]),
        verified_work_ids=["one"],
        verification_failures=[],
        retrieval_requirement=CopyRetrievalRequirement.BASELINE_ALLOWED,
    )

    assert snapshot["coverage_status"] == CoverageStatus.FAILED
    assert snapshot["complete_for_declared_catalog"] is False
    assert "COVERAGE_MANIFEST_INCONSISTENT" in snapshot["coverage_reason_codes"]
