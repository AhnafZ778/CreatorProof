import json
from io import BytesIO

import numpy as np
from PIL import Image


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


def png(color: tuple[int, int, int]) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (220, 160), color).save(buffer, format="PNG")
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
