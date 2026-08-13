from scripts.benchmark_model_system_stress import (
    _structural_stress,
    _style_selection_stress,
)


def test_region_aware_structure_improves_partial_copy_readout() -> None:
    result = _structural_stress()

    assert result["baseline_mask_policy"] == "FULL_VALIDATED_ALIGNMENT_V1"
    assert result["improved_mask_policy"] == "GEOMETRY_VERIFIED_SUPPORT_REGIONS_V1"
    assert result["improved_structure_consensus"] > 0.95
    assert result["absolute_improvement"] > 0.20


def test_style_selection_correction_prevents_naive_false_support() -> None:
    result = _style_selection_stress()

    assert result["naive_false_support_gate_passed"] is True
    assert result["corrected_support_gate_passed"] is False
    assert result["false_support_prevented"] is True
    assert result["selection_adjusted_negative_tail_p"] > result["raw_negative_tail_p"]
