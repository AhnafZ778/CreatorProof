import json
from io import BytesIO

import numpy as np
from PIL import Image

from app.services.retrieval import retrieve_candidates


class ColorVectorProvider:
    """Tiny deterministic test double proving learned-vector ordering beats pHash ties."""

    name = "test-color-vector"
    available = True
    unavailable_reason = None
    device = "cpu"

    def status(self) -> dict:
        return {
            "provider": self.name,
            "available": True,
            "model_path": "test-double",
            "device": self.device,
            "reason": None,
        }

    @staticmethod
    def embed(image: Image.Image) -> np.ndarray:
        vector = np.asarray(image.convert("RGB"), dtype=np.float32).mean(axis=(0, 1))
        norm = float(np.linalg.norm(vector))
        return vector / norm

    @staticmethod
    def similarity(left: np.ndarray, right: np.ndarray) -> float:
        return float(np.dot(left, right))


class RegionalRecallProvider:
    """Deterministic double where a copied region is hidden by whole-image context."""

    name = "test-regional-recall"
    available = True
    unavailable_reason = None
    device = "cpu"

    @staticmethod
    def embed(image: Image.Image) -> np.ndarray:
        rgb = image.convert("RGB")
        if rgb.size == (320, 320):
            vector = np.asarray((0.435, 0.9, 0.0), dtype=np.float32)
            return vector / np.linalg.norm(vector)
        mean = np.asarray(rgb, dtype=np.float32).mean(axis=(0, 1))
        if mean[0] > 200 and mean[1] < 60:
            return np.asarray((1.0, 0.0, 0.0), dtype=np.float32)
        if mean[1] > 200 and mean[0] < 60:
            return np.asarray((0.0, 1.0, 0.0), dtype=np.float32)
        return np.asarray((0.0, 0.0, 1.0), dtype=np.float32)

    @staticmethod
    def embed_many(images: list[Image.Image]) -> list[np.ndarray]:
        return [RegionalRecallProvider.embed(image) for image in images]

    @staticmethod
    def similarity(left: np.ndarray, right: np.ndarray) -> float:
        return float(np.dot(left, right))


def png(color: tuple[int, int, int]) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (220, 160), color).save(buffer, format="PNG")
    return buffer.getvalue()


def regional_query_png() -> bytes:
    image = Image.new("RGB", (320, 320), (0, 0, 255))
    image.paste(Image.new("RGB", (205, 205), (255, 0, 0)), (0, 0))
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def register(client, api_key: str, raw: bytes, title: str):
    return client.post(
        "/v1/works",
        headers={"X-API-Key": api_key},
        data={
            "title": title,
            "catalog_id": "demo-catalog",
            "rights_path": "NO_LICENSE_INFO",
            "allowed_uses": json.dumps([]),
            "claim_state": "ASSERTED",
        },
        files={"file": (f"{title}.png", raw, "image/png")},
    )


def test_unregistered_query_selects_nearest_ai_reference_and_media_is_renderable(client, api_key):
    client.app.state.container.ai_retrieval = ColorVectorProvider()

    red = register(client, api_key, png((255, 0, 0)), "red-reference")
    green = register(client, api_key, png((0, 255, 0)), "green-reference")
    blue = register(client, api_key, png((0, 0, 255)), "blue-reference")
    assert {red.status_code, green.status_code, blue.status_code} == {201}

    query = png((235, 28, 12))
    response = client.post(
        "/v1/scans",
        headers={"X-API-Key": api_key, "Idempotency-Key": "ai-nearest-multi-ref"},
        data={"catalog_id": "demo-catalog", "intended_use": "marketing/social"},
        files={"file": ("unregistered-query.png", query, "image/png")},
    )
    assert response.status_code == 202, response.text
    body = response.json()
    top = body["evidence_packet"]["matches"][0]

    assert top["work_id"] == red.json()["id"]
    assert top["retrieval_rank"] == 1
    assert top["retrieval_provider"] == "test-color-vector"
    assert top["ai_similarity"] is not None
    assert top["exact_sha256"] is False
    # A very strong global score without local geometry is review-only, never a match.
    assert top["verification_state"] == "REVIEW_CANDIDATE"
    assert top["fusion"]["match_supported"] is False
    assert top["fusion"]["review_supported"] is True
    assert top["geometry"]["validated"] is False
    assert top["visualization"]["regions"] == []
    assert top["visualization"]["correspondences"] == []

    media = client.get(
        f"/v1/works/{top['work_id']}/media",
        headers={"X-API-Key": api_key},
    )
    assert media.status_code == 200
    assert media.headers["content-type"] == "image/png"
    assert media.content == png((255, 0, 0))


def test_regional_query_recovers_source_hidden_by_whole_image_context(client, api_key):
    container = client.app.state.container
    container.ai_retrieval = RegionalRecallProvider()
    target = register(client, api_key, png((255, 0, 0)), "regional-target")
    distractor = register(client, api_key, png((0, 255, 0)), "whole-image-distractor")
    assert target.status_code == distractor.status_code == 201

    query_raw = regional_query_png()
    with Image.open(BytesIO(query_raw)) as opened:
        query_image = opened.convert("RGB")
        query_image.load()
    fingerprints = container.fingerprints.compute(query_raw, query_image)

    container.settings.copy_regional_retrieval_enabled = False
    with container.database.session_factory() as db:
        baseline, _, baseline_runtime = retrieve_candidates(
            db,
            container=container,
            candidate_image=query_image,
            tenant_id=container.settings.dev_tenant_id,
            catalog_id="demo-catalog",
            candidate_sha256=fingerprints.sha256,
            candidate_phash=fingerprints.phash,
            top_k=1,
            exhaustive_max_entries=0,
        )
    assert baseline[0].work.id == distractor.json()["id"]
    assert baseline_runtime.regional_query_count == 0

    container.settings.copy_regional_retrieval_enabled = True
    with container.database.session_factory() as db:
        improved, _, improved_runtime = retrieve_candidates(
            db,
            container=container,
            candidate_image=query_image,
            tenant_id=container.settings.dev_tenant_id,
            catalog_id="demo-catalog",
            candidate_sha256=fingerprints.sha256,
            candidate_phash=fingerprints.phash,
            top_k=1,
            exhaustive_max_entries=0,
        )
    recovered = improved[0]

    assert recovered.work.id == target.json()["id"]
    assert recovered.retrieval_rank == 1
    assert recovered.retrieval_view == "region_top_left"
    assert recovered.ai_regional_similarity == 1.0
    assert recovered.ai_similarity < recovered.ai_regional_similarity
    assert improved_runtime.regional_query_count == 5
