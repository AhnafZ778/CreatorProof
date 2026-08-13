import json
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from app.core.config import Settings
from app.domain.enums import ProvenanceStatus
from app.providers.contracts import SyntheticDetectorScore
from app.providers.synthetic_detection import SightengineDetector, SyntheticDetectorRouter
from app.services.synthetic_analysis import analyze_synthetic_origin


def _router(tmp_path, *, api_user: str = "mock_u", api_secret: str = "mock_s"):
    return SyntheticDetectorRouter(
        mode="sightengine",
        sightengine_api_user=api_user,
        sightengine_api_secret=api_secret,
        community_model_path=tmp_path / "community-not-installed",
        torchscript_model_path=tmp_path / "torchscript-not-installed.pt",
        device="cpu",
        external_detectors_json="[]",
        evidence_family_registry_path=tmp_path / "families.json",
        calibration_path=tmp_path / "calibration.json",
        min_calibration_samples=100,
        min_calibration_class_samples=25,
    )


def _settings(**overrides):
    values = {
        "synthetic_spatial_crops": True,
        "synthetic_spatial_crop_fraction": 0.7,
        "synthetic_review_threshold": 0.65,
        "synthetic_likely_threshold": 0.85,
        "synthetic_min_independent_families": 2,
        "synthetic_max_view_std": 0.20,
        "synthetic_min_short_side": 64,
    }
    values.update(overrides)
    return Settings(**values)


def _provenance():
    return MagicMock(
        status=ProvenanceStatus.NOT_PRESENT,
        provider="not-configured",
        manifest_summary=None,
    )


class _FallbackDetector:
    name = "test-local-fallback"
    evidence_family = "TEST_LOCAL_FALLBACK"
    available = True
    unavailable_reason = None

    def __init__(self, score: float = 0.82) -> None:
        self.score = score
        self.calls = 0

    def predict(self, image):
        del image
        self.calls += 1
        return SyntheticDetectorScore(
            provider=self.name,
            score=self.score,
            calibrated=False,
            model_version="test-local-v1",
            evidence_family=self.evidence_family,
            evidence_family_verified=True,
        )


def test_sightengine_detector_initialization_credentials():
    # Split key format user:secret
    detector = SightengineDetector(api_key="my_user_123:my_secret_abc")
    assert detector.available is True
    assert detector.api_user == "my_user_123"
    assert detector.api_secret == "my_secret_abc"
    assert detector.unavailable_reason is None

    # Distinct user and secret
    detector2 = SightengineDetector(api_user="user_456", api_secret="secret_def")
    assert detector2.available is True
    assert detector2.api_user == "user_456"
    assert detector2.api_secret == "secret_def"

    # Missing credentials
    detector_missing = SightengineDetector()
    assert detector_missing.available is False
    assert detector_missing.unavailable_reason == "SIGHTENGINE_API_CREDENTIALS_MISSING"


def test_sightengine_detector_successful_prediction():
    detector = SightengineDetector(api_user="test_user", api_secret="test_secret")
    test_image = Image.new("RGB", (100, 100), color=(255, 128, 0))

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "status": "success",
        "request": {
            "id": "req_123456789",
            "timestamp": 1723300000.0,
            "operations": 1,
        },
        "type": {
            "ai_generated": 0.945,
            "photorealistic": 0.88,
            "details": {
                "midjourney": 0.92,
                "dall_e": 0.05,
            },
        },
        "media": {
            "id": "med_123",
            "uri": "https://api.sightengine.com/1.0/...",
        },
    }

    with patch("httpx.Client.post", return_value=mock_response):
        score = detector.predict(test_image)

    assert isinstance(score, SyntheticDetectorScore)
    assert score.provider == "sightengine-genai"
    assert score.score == pytest.approx(0.945)
    assert score.evidence_family == "SIGHTENGINE_CLOUD_GENAI"
    assert score.details is not None
    assert score.details["photorealistic"] == pytest.approx(0.88)
    assert score.details["request_id"] == "req_123456789"
    assert score.details["generator_details"] == {"midjourney": 0.92, "dall_e": 0.05}


def test_sightengine_posts_original_media_with_the_required_credentials():
    detector = SightengineDetector(api_user="test_user", api_secret="test_secret")
    media = BytesIO()
    Image.new("RGB", (16, 16), "white").save(media, format="PNG")
    response = MagicMock(status_code=200)
    response.json.return_value = {
        "status": "success",
        "request": {"id": "req_media"},
        "type": {"ai_generated": 0.7},
    }
    with patch("httpx.Client.post", return_value=response) as post:
        detector.predict_media(media.getvalue(), filename="private-client-filename.png")

    assert post.call_args.args[0] == "https://api.sightengine.com/1.0/check.json"
    assert post.call_args.kwargs["data"] == {
        "models": "genai",
        "api_user": "test_user",
        "api_secret": "test_secret",
    }
    assert post.call_args.kwargs["files"]["media"][0] == "candidate.png"


def test_sightengine_detector_predict_many_concurrency():
    detector = SightengineDetector(api_user="test_user", api_secret="test_secret", max_workers=2)
    images = [Image.new("RGB", (50, 50), color=(i * 10, i * 20, i * 30)) for i in range(4)]

    def mock_post(url, data=None, files=None):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "status": "success",
            "request": {"id": "req_batch", "timestamp": 1723300000.0},
            "type": {"ai_generated": 0.75, "photorealistic": 0.90},
        }
        return mock_resp

    with patch("httpx.Client.post", side_effect=mock_post):
        results = detector.predict_many(images)

    assert len(results) == 4
    for res in results:
        assert isinstance(res, SyntheticDetectorScore)
        assert res.score == pytest.approx(0.75)


def test_sightengine_detector_error_handling():
    detector = SightengineDetector(api_user="test_user", api_secret="test_secret")
    test_image = Image.new("RGB", (50, 50), color="white")

    # 1. Auth error (401)
    mock_401 = MagicMock()
    mock_401.status_code = 401
    mock_401.text = "Unauthorized"
    with patch("httpx.Client.post", return_value=mock_401):
        with pytest.raises(PermissionError, match="SIGHTENGINE_AUTH_INVALID"):
            detector.predict(test_image)

    # 2. Rate limit (429)
    mock_429 = MagicMock()
    mock_429.status_code = 429
    mock_429.text = "Rate limited"
    with patch("httpx.Client.post", return_value=mock_429):
        with pytest.raises(RuntimeError, match="SIGHTENGINE_RATE_LIMITED"):
            detector.predict(test_image)

    # 3. Sightengine API failure payload
    mock_failure = MagicMock()
    mock_failure.status_code = 200
    mock_failure.json.return_value = {
        "status": "failure",
        "error": {"message": "Invalid image format", "code": 100},
    }
    with patch("httpx.Client.post", return_value=mock_failure):
        with pytest.raises(RuntimeError, match="SIGHTENGINE_API_FAILURE"):
            detector.predict(test_image)


def test_sightengine_is_primary_and_preserves_generator_details(tmp_path):
    test_image = Image.new("RGB", (128, 128), color=(200, 100, 50))

    def mock_post(url, data=None, files=None):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "status": "success",
            "request": {"id": "req_ensemble", "timestamp": 1723300000.0},
            "type": {"ai_generated": 0.88, "ai_generators": {"midjourney": 0.85}},
        }
        return mock_resp

    router = _router(tmp_path)
    assert router.available is True
    assert len(router.detectors) == 1
    assert router.detectors[0].name == "sightengine-genai"

    with patch("httpx.Client.post", side_effect=mock_post):
        result = analyze_synthetic_origin(
            image=test_image,
            detector_router=router,
            provenance=_provenance(),
            settings=_settings(),
            source_media=b"not-a-real-image-but-a-private-original-media-fixture",
            source_filename="candidate.png",
        )

    assert result["classification"] == "AI_ORIGIN_REVIEW_CANDIDATE"
    assert result["fused_detector_score"] == pytest.approx(0.88, rel=0.1)
    assert result["members"][0]["provider_role"] == "PRIMARY"
    assert result["members"][0]["inference_mode"] == "ORIGINAL_MEDIA_UPLOAD"
    assert result["members"][0]["provider_details"]["generator_scores"] == {"midjourney": 0.85}
    assert result["runtime"]["routing"]["primary_succeeded"] is True
    assert result["runtime"]["routing"]["fallback_activated"] is False
    assert "forensic_indicators" in result
    indicators = result["forensic_indicators"]
    assert "spatial_hotspots" in indicators
    assert "transformation_resilience" in indicators
    assert "generator_cues" in indicators
    assert len(indicators["generator_cues"]) >= 1
    cue = indicators["generator_cues"][0]
    assert cue["provider"] == "sightengine-genai"
    assert cue["ai_confidence"] == pytest.approx(0.88)


def test_sightengine_uses_one_original_media_request_not_multiview_calls(tmp_path):
    router = _router(tmp_path)
    test_image = Image.new("RGB", (200, 200), color=(100, 150, 200))

    call_count = 0

    def mock_post(url, data=None, files=None):
        nonlocal call_count
        call_count += 1
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "status": "success",
            "request": {"id": f"req_{call_count}", "timestamp": 1723300000.0},
            "type": {
                "ai_generated": 0.84,
                "ai_generators": {"midjourney": 0.89},
            },
        }
        return mock_resp

    with patch("httpx.Client.post", side_effect=mock_post):
        result = analyze_synthetic_origin(
            image=test_image,
            detector_router=router,
            provenance=_provenance(),
            settings=_settings(),
            source_media=b"original-bytes",
            source_filename="candidate.jpg",
        )

    forensics = result["forensic_indicators"]
    # Sightengine is called once with the real upload. Sending all transformed views
    # would spend multiple requests and could dilute the provider's own verdict.
    assert call_count == 1
    assert forensics["spatial_hotspots"] == []
    assert forensics["transformation_resilience"] == []
    assert result["members"][0]["transform_stability"] is None
    assert result["members"][0]["transform_stability_state"] == "NOT_MEASURED_ORIGINAL_MEDIA_ONLY"


def test_sightengine_failure_activates_local_fallback_without_leaking_credentials(tmp_path):
    router = _router(tmp_path, api_user="private-user", api_secret="private-secret")
    fallback = _FallbackDetector()
    router.fallback_detectors = [fallback]
    router.detectors = [router.primary_detector, fallback]
    response = MagicMock(status_code=429)

    with patch("httpx.Client.post", return_value=response):
        result = analyze_synthetic_origin(
            image=Image.new("RGB", (160, 160), color="white"),
            detector_router=router,
            provenance=_provenance(),
            settings=_settings(synthetic_spatial_crops=False),
            source_media=b"private-original-media",
            source_filename="candidate.png",
        )

    assert fallback.calls == 5
    assert result["runtime"]["routing"]["fallback_activated"] is True
    assert result["runtime"]["routing"]["fallback_reason"] == "PRIMARY_OPERATIONAL_FAILURE"
    assert result["members"][0]["provider"] == "test-local-fallback"
    assert result["members"][0]["provider_role"] == "FALLBACK"
    assert "SIGHTENGINE_RATE_LIMITED" in {error["error_code"] for error in result["errors"]}
    rendered = json.dumps({"result": result, "status": router.status()})
    assert "private-user" not in rendered
    assert "private-secret" not in rendered


def test_valid_low_sightengine_score_does_not_cherry_pick_local_fallback(tmp_path):
    router = _router(tmp_path)
    fallback = _FallbackDetector(score=0.99)
    router.fallback_detectors = [fallback]
    router.detectors = [router.primary_detector, fallback]
    response = MagicMock(status_code=200)
    response.json.return_value = {
        "status": "success",
        "request": {"id": "req_valid_low", "operations": 1},
        "type": {"ai_generated": 0.02},
    }

    with patch("httpx.Client.post", return_value=response):
        result = analyze_synthetic_origin(
            image=Image.new("RGB", (160, 160), color="white"),
            detector_router=router,
            provenance=_provenance(),
            settings=_settings(synthetic_spatial_crops=False),
            source_media=b"approved-original-media",
            source_filename="candidate.png",
        )

    assert fallback.calls == 0
    assert result["members"][0]["provider"] == "sightengine-genai"
    assert result["members"][0]["aggregate_score"] == pytest.approx(0.02)
    assert result["runtime"]["routing"]["primary_succeeded"] is True
    assert result["runtime"]["routing"]["fallback_activated"] is False


def test_unconfigured_sightengine_status_is_explicit_and_secret_free(tmp_path):
    router = _router(tmp_path, api_user="", api_secret="")

    status = router.status()

    assert status["routing"]["primary_provider"] == "sightengine-genai"
    assert status["routing"]["primary_state"] == "UNAVAILABLE"
    assert status["routing"]["primary"]["credentials_configured"] is False
    assert status["routing"]["primary"]["credential_values_exposed"] is False
    assert "api_user" not in json.dumps(status).lower()
    assert "api_secret" not in json.dumps(status).lower()
