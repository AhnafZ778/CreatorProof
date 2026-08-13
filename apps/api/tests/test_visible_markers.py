import shutil

import pytest
from PIL import Image, ImageDraw, ImageFont

from app.providers.visible_markers import VisibleAIMarkerProvider


def _provider(monkeypatch, tsv: str) -> VisibleAIMarkerProvider:
    provider = VisibleAIMarkerProvider(
        mode="off",
        binary="tesseract",
        timeout_seconds=2,
        minimum_confidence=0.4,
        configured_terms_json="[]",
    )
    provider.available = True
    provider.binary_path = "/test/tesseract"
    provider.unavailable_reason = None
    monkeypatch.setattr(provider, "_run_tesseract", lambda path, **kwargs: tsv)
    return provider


def _tsv(*words: tuple[str, int, int, int, int, int]) -> str:
    rows = [
        "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext"
    ]
    for number, (text, left, top, width, height, confidence) in enumerate(words, start=1):
        rows.append(
            f"5\t1\t1\t1\t1\t{number}\t{left}\t{top}\t{width}\t{height}\t{confidence}\t{text}"
        )
    return "\n".join(rows)


def test_explicit_ai_generated_label_is_found_and_localized(monkeypatch):
    provider = _provider(
        monkeypatch,
        _tsv(("AI", 12, 16, 32, 18, 96), ("generated", 50, 16, 92, 18, 94)),
    )

    result = provider.inspect(Image.new("RGB", (640, 420), "white"))

    assert result.classification == "VISIBLE_AI_MARKER_FOUND"
    assert result.supports_ai_origin_review is True
    assert result.markers[0]["kind"] == "EXPLICIT_AI_LABEL"
    assert all(0.0 <= value <= 1.0 for value in result.markers[0]["normalized_box"])


def test_unrelated_visible_text_does_not_become_ai_evidence(monkeypatch):
    provider = _provider(
        monkeypatch,
        _tsv(("Artist", 12, 16, 54, 18, 96), ("portfolio", 72, 16, 82, 18, 95)),
    )

    result = provider.inspect(Image.new("RGB", (640, 420), "white"))

    assert result.classification == "NO_VISIBLE_AI_MARKER_FOUND"
    assert result.supports_ai_origin_review is False


def test_unavailable_ocr_is_not_reported_as_no_label():
    provider = VisibleAIMarkerProvider(
        mode="off",
        binary="tesseract",
        timeout_seconds=2,
        minimum_confidence=0.4,
        configured_terms_json="[]",
    )

    result = provider.inspect(Image.new("RGB", (640, 420), "white"))

    assert result.classification == "VISIBLE_MARKER_ANALYSIS_UNAVAILABLE"
    assert result.checked is False
    assert "not a negative result" in result.limitations[0]


@pytest.mark.skipif(shutil.which("tesseract") is None, reason="Tesseract is not installed")
def test_real_tesseract_detects_a_clear_ai_generated_label():
    image = Image.new("RGB", (1100, 700), "#efe9dc")
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", 72)
    except OSError:
        font = ImageFont.load_default(size=72)
    draw.rounded_rectangle((70, 520, 900, 650), radius=20, fill="black")
    draw.text((105, 545), "AI GENERATED", fill="white", font=font)

    provider = VisibleAIMarkerProvider(
        mode="tesseract",
        binary="tesseract",
        timeout_seconds=8,
        minimum_confidence=0.4,
        configured_terms_json="[]",
    )
    result = provider.inspect(image)

    assert result.checked is True
    assert result.classification == "VISIBLE_AI_MARKER_FOUND"
    assert result.supports_ai_origin_review is True
