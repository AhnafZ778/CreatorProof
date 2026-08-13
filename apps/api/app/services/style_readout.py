from __future__ import annotations

from collections.abc import Mapping, Sequence

import numpy as np


def normalize(vector: np.ndarray) -> np.ndarray:
    vector = np.asarray(vector, dtype=np.float32).reshape(-1)
    norm = float(np.linalg.norm(vector))
    if norm <= 1e-12 or not np.isfinite(vector).all():
        raise ValueError("Invalid style embedding")
    return vector / norm


def _stack(vectors: Mapping[str, np.ndarray], ids: Sequence[str]) -> np.ndarray:
    if not ids:
        raise ValueError("At least one reference vector is required")
    matrix = np.stack([normalize(vectors[item_id]) for item_id in ids]).astype(np.float32)
    if matrix.ndim != 2:
        raise ValueError("Style embeddings must form a two-dimensional matrix")
    return matrix


def corpus_profile_readout(
    query_vector: np.ndarray,
    vectors: Mapping[str, np.ndarray],
    groups: Mapping[str, Sequence[str]],
    *,
    csls_k: int = 15,
) -> dict[str, dict[str, float | int | None]]:
    """Return raw pool cosine and CSD+-style local-density-corrected readouts.

    CSLS is a ranking score, not a probability. Reference local density excludes the
    self-similarity diagonal so an anchor cannot make its own neighbourhood look denser.
    """

    ids = list(vectors)
    matrix = _stack(vectors, ids)
    query = normalize(query_vector)
    query_scores = matrix @ query
    count = len(ids)

    if count >= 2:
        reference_cosines = matrix @ matrix.T
        np.fill_diagonal(reference_cosines, -np.inf)
        anchor_k = max(1, min(int(csls_k), count - 1))
        anchor_density = np.mean(
            np.partition(reference_cosines, count - anchor_k, axis=1)[:, -anchor_k:],
            axis=1,
        )
        query_k = max(1, min(int(csls_k), count))
        query_density = float(np.mean(np.partition(query_scores, count - query_k)[-query_k:]))
    else:
        anchor_k = 0
        anchor_density = np.zeros(1, dtype=np.float32)
        query_density = float(query_scores[0])

    index_by_id = {item_id: index for index, item_id in enumerate(ids)}
    readouts: dict[str, dict[str, float | int | None]] = {}
    for group_key, member_ids in groups.items():
        indices = [index_by_id[item_id] for item_id in member_ids]
        raw_pool_similarity = float(np.mean(query_scores[indices]))
        csls_score = (
            2.0 * raw_pool_similarity - query_density - float(np.mean(anchor_density[indices]))
            if count >= 2
            else None
        )
        readouts[group_key] = {
            "raw_pool_similarity": raw_pool_similarity,
            "csls_score": csls_score,
            "query_local_density": query_density if count >= 2 else None,
            "anchor_local_density": (
                float(np.mean(anchor_density[indices])) if count >= 2 else None
            ),
            "csls_k_effective": anchor_k,
        }
    return readouts


def aggregated_discrimination_gaps(
    vectors: Mapping[str, np.ndarray],
    groups: Mapping[str, Sequence[str]],
) -> dict[str, dict[str, float | str | None]]:
    """Compute leave-one-out, pool-aggregated within-vs-cross creator gaps.

    A negative gap means raw cosine is median-inverted against at least one other
    creator in this exact catalog. It does not mean the encoder contains no useful signal.
    """

    ids = list(vectors)
    matrix = _stack(vectors, ids)
    cosine = matrix @ matrix.T
    index_by_id = {item_id: index for index, item_id in enumerate(ids)}
    results: dict[str, dict[str, float | str | None]] = {}

    for group_key, member_ids in groups.items():
        own = [index_by_id[item_id] for item_id in member_ids]
        other_groups = {key: value for key, value in groups.items() if key != group_key}
        if len(own) < 2 or not other_groups:
            results[group_key] = {
                "within_pool_median": None,
                "worst_cross_pool_median": None,
                "worst_cross_profile_key": None,
                "discrimination_gap": None,
            }
            continue

        within_scores = [
            float(np.mean(cosine[index, [other for other in own if other != index]]))
            for index in own
        ]
        within_median = float(np.median(within_scores))
        cross_rows: list[tuple[float, str]] = []
        for other_key, other_member_ids in other_groups.items():
            other_indices = [index_by_id[item_id] for item_id in other_member_ids]
            per_anchor = [float(np.mean(cosine[index, other_indices])) for index in own]
            cross_rows.append((float(np.median(per_anchor)), other_key))
        worst_cross, worst_key = max(cross_rows, key=lambda item: (item[0], item[1]))
        results[group_key] = {
            "within_pool_median": within_median,
            "worst_cross_pool_median": worst_cross,
            "worst_cross_profile_key": worst_key,
            "discrimination_gap": within_median - worst_cross,
        }
    return results


def catalog_relative_empirical_support(
    query_score: float,
    vectors: Mapping[str, np.ndarray],
    groups: Mapping[str, Sequence[str]],
    target_group: str,
    *,
    min_profile_works: int,
    min_profiles: int,
    min_negatives: int,
) -> dict:
    """Estimate catalog-relative empirical support for one creator profile.

    This is not conformal coverage or universal calibration. Positives are leave-one-out
    similarities within
    the target creator; negatives are every other catalog work measured against the
    target pool. The smoothed tail p-value is valid only for this reference cohort.
    """
    target_ids = list(groups.get(target_group) or [])
    other_ids = [
        item_id
        for group, member_ids in groups.items()
        if group != target_group
        for item_id in member_ids
    ]
    reasons: list[str] = []
    if len(target_ids) < min_profile_works:
        reasons.append("INSUFFICIENT_WITHIN_CREATOR_REFERENCES")
    if len(groups) < min_profiles:
        reasons.append("INSUFFICIENT_CREATOR_COHORT")
    if len(other_ids) < min_negatives:
        reasons.append("INSUFFICIENT_CROSS_CREATOR_NEGATIVES")

    target_matrix = _stack(vectors, target_ids)
    positive_scores: list[float] = []
    if len(target_ids) >= 2:
        cosine = target_matrix @ target_matrix.T
        for index in range(len(target_ids)):
            peers = [column for column in range(len(target_ids)) if column != index]
            positive_scores.append(float(np.mean(cosine[index, peers])))

    negative_scores: list[float] = []
    if other_ids:
        for item_id in other_ids:
            negative = normalize(vectors[item_id])
            negative_scores.append(float(np.mean(target_matrix @ negative)))

    negative_tail_p = (
        (1.0 + sum(score >= query_score for score in negative_scores))
        / (len(negative_scores) + 1.0)
        if negative_scores
        else None
    )
    positive_percentile = (
        (1.0 + sum(score <= query_score for score in positive_scores))
        / (len(positive_scores) + 1.0)
        if positive_scores
        else None
    )
    auc = None
    if positive_scores and negative_scores:
        wins = sum(
            1.0 if positive > negative else 0.5 if positive == negative else 0.0
            for positive in positive_scores
            for negative in negative_scores
        )
        auc = wins / (len(positive_scores) * len(negative_scores))
    ready = not reasons and bool(positive_scores and negative_scores)
    return {
        "state": (
            "CATALOG_RELATIVE_EMPIRICAL_SUPPORT_READY"
            if ready
            else "INSUFFICIENT_EMPIRICAL_SUPPORT"
        ),
        "ready": ready,
        "target_reference_count": len(target_ids),
        "positive_calibration_count": len(positive_scores),
        "negative_calibration_count": len(negative_scores),
        "negative_tail_p": negative_tail_p,
        "positive_support_percentile": positive_percentile,
        "reference_separation_auc": auc,
        "positive_score_median": (float(np.median(positive_scores)) if positive_scores else None),
        "negative_score_max": max(negative_scores) if negative_scores else None,
        "reason_codes": reasons,
        "semantics": (
            "CATALOG_RELATIVE_EMPIRICAL_REFERENCE_COHORT_NOT_CONFORMAL_COVERAGE_OR_PROBABILITY"
        ),
    }
