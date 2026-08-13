import pytest

from app.services.benchmark_statistics import binary_rate, lineage_cluster_bootstrap_interval


def _accuracy(rows: list[dict]) -> float | None:
    return binary_rate(rows, numerator=lambda row: row["correct"])


def test_cluster_bootstrap_counts_lineages_instead_of_transforms():
    rows = [
        {"source_lineage_id": "one", "correct": True},
        {"source_lineage_id": "one", "correct": True},
        {"source_lineage_id": "one", "correct": False},
        {"source_lineage_id": "two", "correct": False},
        {"source_lineage_id": "three", "correct": True},
        {"source_lineage_id": "four", "correct": True},
        {"source_lineage_id": "five", "correct": True},
    ]

    first = lineage_cluster_bootstrap_interval(rows, _accuracy, iterations=500, seed=778)
    second = lineage_cluster_bootstrap_interval(rows, _accuracy, iterations=500, seed=778)

    assert first == second
    assert first["cluster_count"] == 5
    assert first["row_count"] == 7
    assert first["eligible_for_acceptance"] is True
    assert first["lower"] <= first["point_estimate"] <= first["upper"]


def test_cluster_bootstrap_fails_visible_when_lineage_is_missing():
    result = lineage_cluster_bootstrap_interval(
        [
            {"source_lineage_id": "one", "correct": True},
            {"source_lineage_id": "two", "correct": False},
            {"source_lineage_id": None, "correct": True},
        ],
        _accuracy,
        iterations=100,
    )

    assert result["eligible_for_acceptance"] is False
    assert "SOURCE_LINEAGE_MISSING" in result["reason_codes"]


def test_cluster_bootstrap_rejects_misleadingly_small_iteration_count():
    with pytest.raises(ValueError, match="at least 100"):
        lineage_cluster_bootstrap_interval([], _accuracy, iterations=20)
