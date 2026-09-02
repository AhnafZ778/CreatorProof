import base64
import hashlib
import json

import httpx
import pytest
from PIL import Image
from pydantic import ValidationError

from app.container import build_container
from app.core.config import Settings
from app.providers.ai_retrieval import RemoteSSCDVisualEmbeddingProvider
from app.providers.remote_embeddings import (
    EMBEDDING_NORMALIZATION,
    EMBEDDING_RESPONSE_SCHEMA,
    RemoteEmbeddingError,
)
from app.providers.style_retrieval import StyleEmbeddingRouter

SSCD_SHA256 = "9f26bd4c848cc19b73d2ae92eea6e04886f61a7b764ceb7a13aeee62e6a6db56"
CSD_SHA256 = "40e92fad63a361b8136100cd234c42d401ef9b34ff1748234318929ebcc7e7a1"


def _response_for(payload: dict, *, dimensions: int, artifact_sha256: str) -> dict:
    embeddings = []
    for index, image in enumerate(payload["images"]):
        vector = [0.0] * dimensions
        vector[index % dimensions] = 1.0
        embeddings.append(
            {
                "id": image["id"],
                "source_sha256": image["sha256"],
                "vector": vector,
            }
        )
    return {
        "schema_version": EMBEDDING_RESPONSE_SCHEMA,
        "request_id": payload["request_id"],
        "lane": payload["lane"],
        "model_identity": payload["model_identity"],
        "preprocessing_identity": payload["preprocessing_identity"],
        "model_artifact_sha256": artifact_sha256,
        "dimensions": dimensions,
        "normalization": EMBEDDING_NORMALIZATION,
        # Returning a different order proves the adapter correlates by id.
        "embeddings": list(reversed(embeddings)),
    }


def test_remote_sscd_contract_auth_pixel_integrity_and_result_order():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer private-inference-token"
        payload = json.loads(request.content)
        seen.append(payload)
        assert payload["lane"] == "COPY"
        assert payload["dimensions"] == 512
        assert payload["required_normalization"] == EMBEDDING_NORMALIZATION
        assert len(payload["images"]) == 2
        for item in payload["images"]:
            raw = base64.b64decode(item["data_base64"], validate=True)
            assert hashlib.sha256(raw).hexdigest() == item["sha256"]
            assert raw.startswith(b"\x89PNG\r\n\x1a\n")
        return httpx.Response(
            200,
            json=_response_for(payload, dimensions=512, artifact_sha256=SSCD_SHA256),
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = RemoteSSCDVisualEmbeddingProvider(
        endpoint_url="https://inference.example/v1/sscd/embeddings",
        auth_token="private-inference-token",
        expected_sha256=SSCD_SHA256,
        batch_size=2,
        client=client,
    )

    vectors = provider.embed_many(
        [Image.new("RGB", (12, 8), "red"), Image.new("RGB", (7, 11), "blue")]
    )

    assert len(seen) == 1
    assert len(vectors) == 2
    assert vectors[0][0] == pytest.approx(1.0)
    assert vectors[1][1] == pytest.approx(1.0)
    assert all(vector.shape == (512,) for vector in vectors)
    assert provider.status()["last_request_state"] == "SUCCEEDED"
    assert "private-inference-token" not in json.dumps(provider.status())


def test_remote_sscd_retries_only_retryable_operational_failure():
    calls = 0
    sleeps = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(503, json={"error": "temporarily unavailable"})
        payload = json.loads(request.content)
        return httpx.Response(
            200,
            json=_response_for(payload, dimensions=512, artifact_sha256=SSCD_SHA256),
        )

    provider = RemoteSSCDVisualEmbeddingProvider(
        endpoint_url="https://inference.example/v1/sscd/embeddings",
        auth_token="secret",
        expected_sha256=SSCD_SHA256,
        max_attempts=2,
        retry_backoff_seconds=0.125,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=sleeps.append,
    )

    vector = provider.embed(Image.new("RGB", (8, 8), "white"))

    assert vector.shape == (512,)
    assert calls == 2
    assert sleeps == [0.125]


@pytest.mark.parametrize(
    "violation", ["artifact", "extra_field", "not_normalized", "numeric_string"]
)
def test_remote_sscd_fails_closed_on_contract_or_identity_drift(violation):
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        payload = json.loads(request.content)
        response = _response_for(payload, dimensions=512, artifact_sha256=SSCD_SHA256)
        if violation == "artifact":
            response["model_artifact_sha256"] = "b" * 64
        elif violation == "extra_field":
            response["untrusted_metadata"] = {"accept": True}
        elif violation == "not_normalized":
            response["embeddings"][0]["vector"][0] = 0.5
        else:
            response["embeddings"][0]["vector"][0] = "1.0"
        return httpx.Response(200, json=response)

    provider = RemoteSSCDVisualEmbeddingProvider(
        endpoint_url="https://inference.example/v1/sscd/embeddings",
        auth_token="secret",
        expected_sha256=SSCD_SHA256,
        max_attempts=3,
        retry_backoff_seconds=0,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(RemoteEmbeddingError):
        provider.embed(Image.new("RGB", (8, 8), "white"))

    # Contract failures are deterministic and must not consume the retry budget.
    assert calls == 1
    assert provider.status()["last_request_state"] == "FAILED"


def test_remote_csd_router_is_learned_on_success_and_diagnostic_on_failure(tmp_path):
    def success_handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        return httpx.Response(
            200,
            json=_response_for(payload, dimensions=768, artifact_sha256=CSD_SHA256),
        )

    router = StyleEmbeddingRouter(
        mode="remote",
        csd_repo_path=tmp_path / "missing-csd",
        csd_model_path=tmp_path / "missing-csd.bin",
        device="cpu",
        expected_sha256=CSD_SHA256,
        remote_url="https://inference.example/v1/csd/embeddings",
        remote_auth_token="secret",
    )
    router.remote_primary._client = httpx.Client(transport=httpx.MockTransport(success_handler))

    learned = router.embed(Image.new("RGB", (8, 8), "green"))

    assert learned.shape == (768,)
    assert router.learned is True
    assert router.status()["primary_identity"]["endpoint_url"].startswith("https://")

    def auth_failure(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "unauthorized"})

    failed_router = StyleEmbeddingRouter(
        mode="remote",
        csd_repo_path=tmp_path / "missing-csd",
        csd_model_path=tmp_path / "missing-csd.bin",
        device="cpu",
        expected_sha256=CSD_SHA256,
        remote_url="https://inference.example/v1/csd/embeddings",
        remote_auth_token="secret",
    )
    failed_router.remote_primary._client = httpx.Client(transport=httpx.MockTransport(auth_failure))

    diagnostic = failed_router.embed(Image.new("RGB", (8, 8), "green"))

    assert diagnostic.shape == (236,)
    assert failed_router.learned is False
    assert failed_router.fallback_reason.startswith("CSD_REMOTE_RUNTIME_FALLBACK")


def test_remote_provider_settings_require_auth_and_https_in_production():
    with pytest.raises(ValidationError, match="CREATORPROOF_SSCD_REMOTE_AUTH_TOKEN"):
        Settings(
            sscd_provider="remote",
            sscd_remote_url="https://inference.example/v1/sscd/embeddings",
        )

    with pytest.raises(ValidationError, match="must use HTTPS in production"):
        Settings(
            environment="production",
            storage_provider="s3",
            s3_bucket="creatorproof-test",
            s3_region="us-east-1",
            s3_access_key_id="test-access-key",
            s3_secret_access_key="test-secret-key",
            sscd_provider="remote",
            sscd_remote_url="http://inference.example/v1/sscd/embeddings",
            sscd_remote_auth_token="secret",
        )


def test_container_selects_remote_sscd_and_csd_without_local_artifacts(tmp_path):
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'remote-wiring.db'}",
        storage_root=tmp_path / "objects",
        job_backend="inline",
        proof_anchor_mode="none",
        model_bundle_path=tmp_path / "model-bundle-not-required.json",
        style_profile_manifest_path=tmp_path / "style-profiles-not-required.json",
        sscd_provider="remote",
        sscd_expected_sha256=SSCD_SHA256,
        sscd_remote_url="https://inference.example/v1/sscd/embeddings",
        sscd_remote_auth_token="copy-secret",
        style_provider="remote",
        style_csd_expected_sha256=CSD_SHA256,
        style_remote_url="https://inference.example/v1/csd/embeddings",
        style_remote_auth_token="style-secret",
        synthetic_detector="sightengine_only",
        sightengine_api_user="sightengine-user",
        sightengine_api_secret="sightengine-secret",
        c2pa_mode="off",
        visible_ai_marker_mode="off",
    )

    container = build_container(settings)
    try:
        assert isinstance(container.ai_retrieval, RemoteSSCDVisualEmbeddingProvider)
        assert container.ai_retrieval.available is True
        assert container.style_retrieval.mode == "remote"
        assert container.style_retrieval.primary is container.style_retrieval.remote_primary
        assert container.style_retrieval.learned is True
        assert container.synthetic_detection.fallback_detectors == []
    finally:
        container.database.engine.dispose()


def test_container_refuses_unpinned_remote_model_identity(tmp_path):
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'unpinned.db'}",
        storage_root=tmp_path / "objects",
        job_backend="inline",
        proof_anchor_mode="none",
        model_bundle_path=tmp_path / "missing-model-bundle.json",
        sscd_provider="remote",
        sscd_remote_url="https://inference.example/v1/sscd/embeddings",
        sscd_remote_auth_token="copy-secret",
        style_provider="diagnostic",
        synthetic_detector="off",
        c2pa_mode="off",
        visible_ai_marker_mode="off",
    )

    with pytest.raises(RuntimeError, match="CREATORPROOF_SSCD_EXPECTED_SHA256"):
        build_container(settings)
