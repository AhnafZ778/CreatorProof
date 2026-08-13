from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from app.core.config import Settings
from app.main import create_app


@pytest.fixture
def api_key() -> str:
    return "test-api-key-123"


@pytest.fixture
def scan_headers(api_key) -> dict[str, str]:
    return {
        "X-API-Key": api_key,
        "Idempotency-Key": "diagnostic-default-scan",
    }


@pytest.fixture
def client(tmp_path, api_key):
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        storage_root=tmp_path / "objects",
        job_backend="inline",
        dev_api_key=api_key,
        proof_log_path=tmp_path / "proof-log.jsonl",
        proof_anchor_mode="none",
        sscd_model_path=tmp_path / "models" / "sscd-not-installed.pt",
        style_provider="diagnostic",
        synthetic_detector="off",
        synthetic_policy_mode="INFORMATIONAL",
        c2pa_mode="off",
        visible_ai_marker_mode="off",
        copy_retrieval_requirement="BASELINE_ALLOWED",
    )
    app = create_app(settings)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def image_bytes():
    def make(seed: int = 0) -> bytes:
        image = Image.new("RGB", (320, 240), (245, 246, 248))
        draw = ImageDraw.Draw(image)
        draw.rectangle(
            (30 + seed, 30, 145 + seed, 155), fill=(20, 105, 220), outline=(4, 20, 40), width=5
        )
        draw.ellipse(
            (165, 55 + seed, 275, 165 + seed), fill=(250, 160, 40), outline=(70, 30, 5), width=4
        )
        draw.line((20, 205, 300, 185 - seed), fill=(25, 30, 40), width=7)
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        return buffer.getvalue()

    return make
