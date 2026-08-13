import json
from dataclasses import dataclass

from PIL import Image

from app.core.config import Settings
from app.domain.enums import ProvenanceStatus
from app.providers.contracts import ProvenanceEvidence, SyntheticDetectorScore
from app.providers.synthetic_detection import (
    ExternalJsonSyntheticDetector,
    SyntheticCalibrationRegistry,
    SyntheticEvidenceFamilyRegistry,
    _community_forensics_crop,
)
from app.services.synthetic_analysis import analyze_synthetic_origin


@dataclass
class SequenceDetector:
    values: list[float]
    name: str = "test-detector"
    evidence_family: str = "SEMANTIC_TEST"
    calibrated: bool = False
    available: bool = True
    unavailable_reason: str | None = None

    def predict(self, image):
        del image
        value = self.values.pop(0)
        return SyntheticDetectorScore(
            provider=self.name,
            score=value,
            calibrated=self.calibrated,
            model_version="test-v1",
            evidence_family=self.evidence_family,
            evidence_family_verified=True,
        )


class Router:
    def __init__(self, detectors):
        self.detectors = detectors
        self.calibrated_providers = {detector.name for detector in detectors if detector.calibrated}

    def calibrate(
        self,
        provider,
        model_version,
        score,
        artifact_sha256=None,
        preprocessing_identity=None,
    ):
        del model_version, artifact_sha256, preprocessing_identity
        applied = provider in self.calibrated_providers
        return score, {
            "applied": applied,
            "state": "TEST_REGISTRY_CALIBRATED" if applied else "TEST_UNCALIBRATED",
            "semantics": (
                "TEST_HELD_OUT_CALIBRATION" if applied else "RAW_DETECTOR_SCORE_NOT_PROBABILITY"
            ),
        }


def _image():
    return Image.new("RGB", (256, 256), "#667788")


def _provenance(status=ProvenanceStatus.NOT_PRESENT, manifest=None):
    return ProvenanceEvidence(
        status=status,
        provider="test-provenance",
        reason_codes=[],
        manifest_summary=manifest,
    )


def _settings(**overrides):
    return Settings(synthetic_spatial_crops=False, **overrides)


def test_stable_single_detector_can_raise_review_but_not_claim_confident_origin():
    result = analyze_synthetic_origin(
        image=_image(),
        detector_router=Router([SequenceDetector([0.92] * 5)]),
        provenance=_provenance(),
        settings=_settings(),
    )

    assert result["classification"] == "AI_ORIGIN_REVIEW_CANDIDATE"
    assert result["transform_stability"] == 1.0
    assert result["detector_count"] == 1
    assert result["evidence_family_count"] == 1
    assert result["presentation"]["show_domain_score"] is False
    assert "SINGLE_DETECTOR_LIMITATION" in result["reason_codes"]


def test_single_uncalibrated_low_score_abstains_instead_of_implying_human_origin():
    result = analyze_synthetic_origin(
        image=_image(),
        detector_router=Router([SequenceDetector([0.01] * 5)]),
        provenance=_provenance(),
        settings=_settings(),
    )

    assert result["classification"] == "AI_ORIGIN_INCONCLUSIVE_LIMITED_COVERAGE"
    assert result["review_recommended"] is True
    assert result["negative_clearance_supported"] is False
    assert result["presentation"]["state"] == "ORIGIN_UNKNOWN"
    assert result["presentation"]["domain_score"] is None


def test_transform_instability_keeps_a_strong_original_signal_in_review():
    result = analyze_synthetic_origin(
        image=_image(),
        detector_router=Router([SequenceDetector([0.97, 0.04, 0.91, 0.08, 0.88])]),
        provenance=_provenance(),
        settings=_settings(),
    )

    # Delivery transformations now measure robustness but cannot average a strong
    # original-image response down into a false quiet score. Instability still blocks
    # any high-confidence claim and stays visibly review-only.
    assert result["classification"] == "AI_ORIGIN_REVIEW_CANDIDATE"
    assert result["evidence_tier"] == "REVIEW"
    assert result["members"][0]["original_score"] == 0.97
    assert result["members"][0]["aggregate_score"] == 0.97
    assert "TRANSFORM_SENSITIVE_SIGNAL_RETAINS_REVIEW_ONLY" in result["reason_codes"]


def test_trusted_c2pa_ai_assertion_overrides_missing_detector():
    result = analyze_synthetic_origin(
        image=_image(),
        detector_router=Router([]),
        provenance=_provenance(
            ProvenanceStatus.VALID_TRUSTED,
            {"ai_assertion_present": True},
        ),
        settings=_settings(),
    )

    assert result["classification"] == "AI_PROVENANCE_CONFIRMED"
    assert result["evidence_tier"] == "PROVENANCE"
    assert result["fused_detector_score"] is None


def test_no_detector_does_not_claim_human_origin():
    result = analyze_synthetic_origin(
        image=_image(),
        detector_router=Router([]),
        provenance=_provenance(),
        settings=_settings(),
    )

    assert result["classification"] == "SYNTHETIC_ORIGIN_ANALYSIS_UNAVAILABLE"
    assert "NO_SYNTHETIC_DETECTOR_ACTIVE" in result["reason_codes"]


def test_visible_ai_label_routes_no_model_case_to_review_and_restores_scores():
    visible_marker = {
        "provider": "test-visible-marker",
        "available": True,
        "checked": True,
        "classification": "VISIBLE_AI_MARKER_FOUND",
        "supports_ai_origin_review": True,
        "marker_strength": 0.94,
        "markers": [
            {
                "kind": "EXPLICIT_AI_LABEL",
                "recognized_text": "AI generated",
                "ocr_confidence": 0.93,
                "normalized_box": [0.72, 0.88, 0.96, 0.97],
            }
        ],
        "reason_codes": ["EXPLICIT_VISIBLE_AI_LABEL_FOUND"],
    }
    result = analyze_synthetic_origin(
        image=_image(),
        detector_router=Router([]),
        provenance=_provenance(),
        settings=_settings(),
        visible_marker=visible_marker,
    )

    assert result["classification"] == "AI_ORIGIN_MARKER_FOUND"
    assert result["review_recommended"] is True
    assert result["presentation"]["headline"] == "A visible AI label was found"
    assert result["scorecard"]["signal_score"] == 94
    assert result["scorecard"]["score_semantics"].endswith("NOT_AI_PROBABILITY")


def test_missing_visible_label_is_neutral_not_human_evidence():
    result = analyze_synthetic_origin(
        image=_image(),
        detector_router=Router([]),
        provenance=_provenance(),
        settings=_settings(),
        visible_marker={
            "classification": "NO_VISIBLE_AI_MARKER_FOUND",
            "supports_ai_origin_review": False,
            "marker_strength": 0.0,
            "markers": [],
            "reason_codes": ["NO_CONFIGURED_VISIBLE_AI_LABEL_RECOGNIZED"],
        },
    )

    marker_factor = next(
        item for item in result["scorecard"]["factors"] if item["id"] == "visible_label"
    )
    assert result["classification"] == "SYNTHETIC_ORIGIN_ANALYSIS_UNAVAILABLE"
    assert marker_factor["signal_score"] is None
    assert "Neutral result" in marker_factor["detail"]


def test_two_independent_stable_families_can_support_likely_ai():
    result = analyze_synthetic_origin(
        image=_image(),
        detector_router=Router(
            [
                SequenceDetector(
                    [0.91] * 5,
                    name="semantic-model",
                    evidence_family="SEMANTIC",
                    calibrated=True,
                ),
                SequenceDetector(
                    [0.86] * 5,
                    name="pixel-model",
                    evidence_family="PIXEL_FREQUENCY",
                    calibrated=True,
                ),
            ]
        ),
        provenance=_provenance(),
        settings=_settings(),
    )

    assert result["classification"] == "LIKELY_AI_GENERATED"
    assert result["positive_family_count"] == 2
    assert result["presentation"]["state"] == "AI_INDICATORS_FOUND"
    assert result["presentation"]["show_domain_score"] is True


def test_two_uncalibrated_strong_families_remain_review_only():
    result = analyze_synthetic_origin(
        image=_image(),
        detector_router=Router(
            [
                SequenceDetector(
                    [0.91] * 5,
                    name="semantic-model",
                    evidence_family="SEMANTIC",
                    calibrated=False,
                ),
                SequenceDetector(
                    [0.86] * 5,
                    name="pixel-model",
                    evidence_family="PIXEL_FREQUENCY",
                    calibrated=False,
                ),
            ]
        ),
        provenance=_provenance(),
        settings=_settings(),
    )

    assert result["classification"] == "AI_ORIGIN_REVIEW_CANDIDATE"
    assert result["evidence_tier"] == "REVIEW"
    assert "DEPLOYMENT_CALIBRATION_INCOMPLETE" in result["reason_codes"]


def test_two_calibrated_quiet_families_can_report_no_strong_signal():
    result = analyze_synthetic_origin(
        image=_image(),
        detector_router=Router(
            [
                SequenceDetector(
                    [0.12] * 5,
                    name="semantic-model",
                    evidence_family="SEMANTIC",
                    calibrated=True,
                ),
                SequenceDetector(
                    [0.18] * 5,
                    name="pixel-model",
                    evidence_family="PIXEL_FREQUENCY",
                    calibrated=True,
                ),
            ]
        ),
        provenance=_provenance(),
        settings=_settings(),
    )

    assert result["classification"] == "NO_AI_ORIGIN_EVIDENCE_DETECTED"
    assert result["negative_clearance_supported"] is True
    assert result["review_recommended"] is False
    assert "does not prove human origin" in result["presentation"]["summary"].lower()


def test_independent_family_disagreement_abstains():
    result = analyze_synthetic_origin(
        image=_image(),
        detector_router=Router(
            [
                SequenceDetector(
                    [0.92] * 5,
                    name="semantic-model",
                    evidence_family="SEMANTIC",
                    calibrated=True,
                ),
                SequenceDetector(
                    [0.08] * 5,
                    name="pixel-model",
                    evidence_family="PIXEL_FREQUENCY",
                    calibrated=True,
                ),
            ]
        ),
        provenance=_provenance(),
        settings=_settings(),
    )

    assert result["classification"] == "INCONCLUSIVE_DETECTOR_DISAGREEMENT"
    assert result["review_recommended"] is True


def test_spatial_consensus_can_recover_a_signal_lost_by_global_reduction():
    result = analyze_synthetic_origin(
        image=_image(),
        detector_router=Router([SequenceDetector([0.10] * 5 + [0.88] * 5)]),
        provenance=_provenance(),
        settings=Settings(synthetic_spatial_crops=True),
    )

    member = result["members"][0]
    assert member["global_delivery_score"] == 0.1
    assert member["spatial_corroborated"] is True
    assert member["spatial_support_count"] == 5
    assert member["aggregate_score"] == 0.88
    assert result["classification"] == "AI_ORIGIN_REVIEW_CANDIDATE"


def test_community_forensics_preprocessing_matches_official_resize_then_center_crop():
    image = Image.new("RGB", (1000, 500), "#00ff00")
    for x in range(250, 268):
        for y in range(500):
            image.putpixel((x, y), (255, 0, 0))
    for x in range(732, 750):
        for y in range(500):
            image.putpixel((x, y), (0, 0, 255))

    cropped = _community_forensics_crop(image)

    assert cropped.size == (384, 384)
    assert cropped.getpixel((0, 192))[1] > 240
    assert cropped.getpixel((383, 192))[1] > 240


def test_calibration_registry_requires_support_and_model_version_match(tmp_path):
    path = tmp_path / "calibration.json"
    path.write_text(
        json.dumps(
            {
                "schema": "creatorproof.synthetic_calibration.v2",
                "providers": {
                    "test-detector": {
                        "slope": 1.2,
                        "intercept": -0.4,
                        "model_version": "test-v1",
                        "artifact_sha256": "a" * 64,
                        "preprocessing_identity": "preprocess-v1",
                        "domain_id": "domain-v1",
                        "crop_policy_id": "crop-v1",
                        "corpus_manifest_set_digest_sha256": "b" * 64,
                        "model_bundle_manifest_digest_sha256": "c" * 64,
                        "sample_count": 200,
                        "positive_count": 100,
                        "negative_count": 100,
                        "dataset_id": "held-out-demo",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    registry = SyntheticCalibrationRegistry(
        path,
        min_samples=100,
        min_class_samples=25,
        expected_domain_id="domain-v1",
        expected_crop_policy_id="crop-v1",
        expected_model_bundle_manifest_digest="c" * 64,
    )

    calibrated, details = registry.apply("test-detector", "test-v1", 0.8, "a" * 64, "preprocess-v1")
    unchanged, mismatch = registry.apply(
        "test-detector", "different-version", 0.8, "a" * 64, "preprocess-v1"
    )

    assert details["applied"] is True
    assert calibrated != 0.8
    assert mismatch["state"] == "MODEL_VERSION_MISMATCH"
    assert unchanged == 0.8


def test_calibration_registry_rejects_artifact_or_domain_drift(tmp_path):
    path = tmp_path / "calibration.json"
    path.write_text(
        json.dumps(
            {
                "schema": "creatorproof.synthetic_calibration.v2",
                "providers": {
                    "test-detector": {
                        "slope": 1.2,
                        "intercept": -0.4,
                        "model_version": "test-v1",
                        "artifact_sha256": "a" * 64,
                        "preprocessing_identity": "preprocess-v1",
                        "domain_id": "domain-v1",
                        "crop_policy_id": "crop-v1",
                        "dataset_id": "held-out-demo",
                        "corpus_manifest_set_digest_sha256": "c" * 64,
                        "model_bundle_manifest_digest_sha256": "d" * 64,
                        "sample_count": 200,
                        "positive_count": 100,
                        "negative_count": 100,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    registry = SyntheticCalibrationRegistry(
        path,
        min_samples=100,
        min_class_samples=25,
        expected_domain_id="different-domain",
        expected_crop_policy_id="crop-v1",
        expected_model_bundle_manifest_digest="d" * 64,
    )

    score, details = registry.apply(
        "test-detector",
        "test-v1",
        0.8,
        artifact_sha256="b" * 64,
        preprocessing_identity="preprocess-v1",
    )

    assert score == 0.8
    assert details["applied"] is False
    assert details["state"] == "CALIBRATION_CONTEXT_MISMATCH"
    assert details["mismatched_fields"] == ["domain_id", "artifact_sha256"]


def test_external_detector_cannot_self_declare_calibration():
    detector = ExternalJsonSyntheticDetector(
        {
            "name": "external-test",
            "command": "/bin/true {image}",
            "allow_declared_calibration": True,
            "evidence_family": "OPERATOR_ASSERTED_FAMILY",
        }
    )

    score = detector._parse_score(
        {
            "score": 0.91,
            "calibrated": True,
            "version": "external-v1",
            "artifact_sha256": "a" * 64,
            "preprocessing_identity": "external-preprocess-v1",
        }
    )

    assert score.calibrated is False
    assert "EXTERNAL_PROVIDER_CALIBRATION_DECLARATION_IGNORED" in score.warnings


def test_family_registry_rejects_unregistered_and_identity_drift(tmp_path):
    path = tmp_path / "families.json"
    path.write_text(
        json.dumps(
            {
                "schema": "creatorproof.synthetic_evidence_family_registry.v1",
                "entries": [
                    {
                        "provider": "registered",
                        "evidence_family": "PIXEL_FORENSICS",
                        "lineage_id": "lineage-v1",
                        "model_version": "v1",
                        "artifact_sha256": "a" * 64,
                        "preprocessing_identity": "preprocess-v1",
                        "review_state": "APPROVED_FOR_FAMILY_COUNTING",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    registry = SyntheticEvidenceFamilyRegistry(path)
    base = SyntheticDetectorScore(
        provider="registered",
        score=0.8,
        calibrated=False,
        model_version="v1",
        artifact_sha256="a" * 64,
        preprocessing_identity="preprocess-v1",
        evidence_family="OPERATOR_CHOSEN",
    )

    approved = registry.govern(base, object())
    drifted = registry.govern(
        SyntheticDetectorScore(
            provider="registered",
            score=0.8,
            calibrated=False,
            model_version="v1",
            artifact_sha256="b" * 64,
            preprocessing_identity="preprocess-v1",
        ),
        object(),
    )
    unregistered = registry.govern(
        SyntheticDetectorScore(provider="unknown", score=0.8, calibrated=False),
        object(),
    )

    assert approved.evidence_family == "PIXEL_FORENSICS"
    assert approved.evidence_family_verified is True
    assert drifted.evidence_family_verified is False
    assert unregistered.evidence_family_verified is False
