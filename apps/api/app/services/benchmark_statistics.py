from __future__ import annotations

from collections.abc import Callable, Sequence

import numpy as np

Statistic = Callable[[list[dict]], float | None]


def binary_rate(
    rows: Sequence[dict],
    *,
    numerator: Callable[[dict], bool],
    denominator: Callable[[dict], bool] | None = None,
) -> float | None:
    selected = [row for row in rows if denominator is None or denominator(row)]
    if not selected:
        return None
    return sum(bool(numerator(row)) for row in selected) / len(selected)


def lineage_cluster_bootstrap_interval(
    rows: Sequence[dict],
    statistic: Statistic,
    *,
    cluster_field: str = "source_lineage_id",
    iterations: int = 2000,
    confidence: float = 0.95,
    seed: int = 778,
    minimum_clusters: int = 5,
) -> dict:
    """Resample independent source lineages, never their transformations as IID rows."""

    if iterations < 100:
        raise ValueError("cluster bootstrap requires at least 100 iterations")
    if not 0.5 < confidence < 1.0:
        raise ValueError("cluster bootstrap confidence must be between 0.5 and 1")
    grouped: dict[str, list[dict]] = {}
    missing_cluster_rows = 0
    for row in rows:
        cluster = str(row.get(cluster_field) or "").strip()
        if not cluster:
            missing_cluster_rows += 1
            continue
        grouped.setdefault(cluster, []).append(dict(row))
    point = statistic([dict(row) for row in rows])
    cluster_ids = sorted(grouped)
    result = {
        "method": "SOURCE_LINEAGE_CLUSTER_PERCENTILE_BOOTSTRAP_V1",
        "confidence": confidence,
        "iterations": iterations,
        "seed": seed,
        "cluster_field": cluster_field,
        "cluster_count": len(cluster_ids),
        "row_count": len(rows),
        "missing_cluster_row_count": missing_cluster_rows,
        "point_estimate": point,
        "lower": None,
        "upper": None,
        "eligible_for_acceptance": False,
        "reason_codes": [],
    }
    if missing_cluster_rows:
        result["reason_codes"].append("SOURCE_LINEAGE_MISSING")
    if point is None:
        result["reason_codes"].append("METRIC_UNAVAILABLE")
        return result
    if len(cluster_ids) < 2:
        result["reason_codes"].append("INSUFFICIENT_SOURCE_LINEAGE_CLUSTERS")
        return result

    rng = np.random.default_rng(seed)
    samples: list[float] = []
    for _ in range(iterations):
        selected = rng.choice(cluster_ids, size=len(cluster_ids), replace=True)
        sampled_rows = [row for cluster in selected for row in grouped[str(cluster)]]
        value = statistic(sampled_rows)
        if value is not None and np.isfinite(value):
            samples.append(float(value))
    if not samples:
        result["reason_codes"].append("BOOTSTRAP_METRIC_UNAVAILABLE")
        return result
    alpha = (1.0 - confidence) / 2.0
    result["lower"] = float(np.quantile(samples, alpha))
    result["upper"] = float(np.quantile(samples, 1.0 - alpha))
    result["eligible_for_acceptance"] = bool(
        len(cluster_ids) >= minimum_clusters and not missing_cluster_rows
    )
    if len(cluster_ids) < minimum_clusters:
        result["reason_codes"].append("MINIMUM_SOURCE_LINEAGE_CLUSTERS_NOT_MET")
    return result
