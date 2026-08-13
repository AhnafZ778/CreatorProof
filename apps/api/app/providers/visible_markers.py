from __future__ import annotations

import csv
import io
import json
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageEnhance, ImageOps

from app.providers.contracts import VisibleMarkerEvidence

_EXPLICIT_AI_PATTERNS = (
    # OCR commonly reads the capital I in "AI" as l, 1, or a separate glyph.
    re.compile(r"\ba\s*[il1|][\s-]*generated\b", re.IGNORECASE),
    re.compile(r"\bgenerated\s+(?:by|with|using)\s+ai\b", re.IGNORECASE),
    re.compile(r"\b(?:made|created)\s+(?:by|with|using)\s+ai\b", re.IGNORECASE),
    re.compile(r"\bsynthetic[\s-]*image\b", re.IGNORECASE),
)


@dataclass(frozen=True, slots=True)
class _OCRView:
    name: str
    image: Image.Image
    source_box: tuple[int, int, int, int]


def _normalize_text(value: str) -> str:
    lowered = value.casefold().replace("_", " ")
    return " ".join(re.sub(r"[^a-z0-9+.-]+", " ", lowered).split())


def _configured_terms(raw: str) -> tuple[str, ...]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return ()
    if not isinstance(payload, list):
        return ()
    terms = []
    for item in payload:
        if isinstance(item, str) and _normalize_text(item):
            terms.append(_normalize_text(item))
    return tuple(dict.fromkeys(terms))


def _views(image: Image.Image) -> list[_OCRView]:
    rgb = ImageOps.exif_transpose(image).convert("RGB")
    width, height = rgb.size
    crop_width = max(32, round(width * 0.46))
    crop_height = max(32, round(height * 0.46))
    boxes = {
        "full_image": (0, 0, width, height),
        "top_left": (0, 0, crop_width, crop_height),
        "top_right": (width - crop_width, 0, width, crop_height),
        "bottom_left": (0, height - crop_height, crop_width, height),
        "bottom_right": (width - crop_width, height - crop_height, width, height),
    }
    return [_OCRView(name, rgb.crop(box), box) for name, box in boxes.items()]


def _prepare_for_ocr(image: Image.Image) -> Image.Image:
    gray = ImageOps.autocontrast(ImageOps.grayscale(image))
    gray = ImageEnhance.Contrast(gray).enhance(1.45)
    shortest = max(1, min(gray.size))
    longest = max(gray.size)
    scale = max(1.0, min(4.0, 760.0 / shortest, 1800.0 / longest))
    if scale > 1.01:
        gray = gray.resize(
            (round(gray.width * scale), round(gray.height * scale)),
            Image.Resampling.LANCZOS,
        )
    return gray


def _line_rows(tsv: str, minimum_confidence: float) -> list[dict]:
    grouped: dict[tuple[str, str, str, str], list[dict]] = {}
    reader = csv.DictReader(io.StringIO(tsv), delimiter="\t")
    for row in reader:
        text = str(row.get("text") or "").strip()
        if not text:
            continue
        try:
            confidence = float(row.get("conf") or -1.0) / 100.0
            left = int(row.get("left") or 0)
            top = int(row.get("top") or 0)
            width = int(row.get("width") or 0)
            height = int(row.get("height") or 0)
        except (TypeError, ValueError):
            continue
        if confidence < minimum_confidence or width <= 0 or height <= 0:
            continue
        key = (
            str(row.get("page_num") or "0"),
            str(row.get("block_num") or "0"),
            str(row.get("par_num") or "0"),
            str(row.get("line_num") or "0"),
        )
        grouped.setdefault(key, []).append(
            {
                "text": text,
                "confidence": confidence,
                "left": left,
                "top": top,
                "right": left + width,
                "bottom": top + height,
            }
        )

    lines = []
    for words in grouped.values():
        words.sort(key=lambda item: item["left"])
        lines.append(
            {
                "text": " ".join(str(item["text"]) for item in words),
                "confidence": sum(float(item["confidence"]) for item in words) / len(words),
                "left": min(int(item["left"]) for item in words),
                "top": min(int(item["top"]) for item in words),
                "right": max(int(item["right"]) for item in words),
                "bottom": max(int(item["bottom"]) for item in words),
            }
        )
    return lines


class VisibleAIMarkerProvider:
    """Find explicit visible AI labels without treating their absence as evidence.

    Visible labels are useful review signals but are forgeable and can also be added to
    human-made media. They therefore never become trusted provenance on their own.
    """

    name = "tesseract-visible-ai-marker-v1"

    def __init__(
        self,
        *,
        mode: str,
        binary: str,
        timeout_seconds: int,
        minimum_confidence: float,
        configured_terms_json: str,
    ) -> None:
        self.mode = mode
        self.binary = binary
        self.timeout_seconds = timeout_seconds
        self.minimum_confidence = minimum_confidence
        self.configured_terms = _configured_terms(configured_terms_json)
        self.binary_path = shutil.which(binary) if mode != "off" else None
        self.available = bool(self.binary_path)
        self.unavailable_reason = (
            None
            if self.available
            else "VISIBLE_MARKER_CHECK_DISABLED"
            if mode == "off"
            else "TESSERACT_BINARY_NOT_FOUND"
        )

    def status(self) -> dict:
        return {
            "provider": self.name,
            "available": self.available,
            "reason": self.unavailable_reason,
            "configured_term_count": len(self.configured_terms),
            "semantics": "VISIBLE_LABEL_REVIEW_SIGNAL_NOT_PROVENANCE",
        }

    def _run_tesseract(
        self,
        path: Path,
        *,
        deadline: float | None = None,
    ) -> tuple[str, ...]:
        if not self.binary_path:
            raise RuntimeError(self.unavailable_reason or "TESSERACT_UNAVAILABLE")
        outputs = []
        for page_segmentation_mode in ("11", "6"):
            remaining = (
                float(self.timeout_seconds) if deadline is None else deadline - time.monotonic()
            )
            if remaining <= 0:
                raise TimeoutError("VISIBLE_MARKER_SCAN_BUDGET_EXHAUSTED")
            completed = subprocess.run(
                [
                    self.binary_path,
                    str(path),
                    "stdout",
                    "--psm",
                    page_segmentation_mode,
                    "-l",
                    "eng",
                    "tsv",
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=max(0.1, remaining),
            )
            if completed.returncode == 0:
                outputs.append(completed.stdout)
        if not outputs:
            raise RuntimeError("TESSERACT_NONZERO_EXIT")
        return tuple(outputs)

    def _match(self, text: str) -> tuple[str, str] | None:
        normalized = _normalize_text(text)
        for pattern in _EXPLICIT_AI_PATTERNS:
            match = pattern.search(normalized)
            if match:
                return "EXPLICIT_AI_LABEL", match.group(0)
        for term in self.configured_terms:
            if term in normalized:
                return "CONFIGURED_GENERATOR_MARK", term
        return None

    def inspect(self, image: Image.Image) -> VisibleMarkerEvidence:
        if not self.available:
            return VisibleMarkerEvidence(
                provider=self.name,
                available=False,
                checked=False,
                classification="VISIBLE_MARKER_ANALYSIS_UNAVAILABLE",
                supports_ai_origin_review=False,
                reason_codes=(self.unavailable_reason or "VISIBLE_MARKER_ANALYSIS_UNAVAILABLE",),
                limitations=("An unavailable visible-marker check is not a negative result.",),
            )

        source_width, source_height = image.size
        markers: dict[tuple[str, str], dict] = {}
        successful_views = 0
        errors: list[str] = []
        deadline = time.monotonic() + self.timeout_seconds
        with tempfile.TemporaryDirectory(prefix="creatorproof-visible-marker-") as temp_directory:
            temp_root = Path(temp_directory)
            for index, view in enumerate(_views(image)):
                prepared = _prepare_for_ocr(view.image)
                path = temp_root / f"view-{index}.png"
                prepared.save(path, format="PNG")
                try:
                    raw_outputs = self._run_tesseract(path, deadline=deadline)
                except (OSError, RuntimeError, TimeoutError, subprocess.TimeoutExpired) as exc:
                    errors.append(f"{view.name}:{type(exc).__name__}")
                    continue
                successful_views += 1
                source_left, source_top, source_right, source_bottom = view.source_box
                source_crop_width = max(1, source_right - source_left)
                source_crop_height = max(1, source_bottom - source_top)
                outputs = (raw_outputs,) if isinstance(raw_outputs, str) else raw_outputs
                for tsv in outputs:
                    for line in _line_rows(tsv, self.minimum_confidence):
                        matched = self._match(str(line["text"]))
                        if not matched:
                            continue
                        kind, phrase = matched
                        normalized_box = [
                            round(
                                (source_left + line["left"] / prepared.width * source_crop_width)
                                / source_width,
                                6,
                            ),
                            round(
                                (source_top + line["top"] / prepared.height * source_crop_height)
                                / source_height,
                                6,
                            ),
                            round(
                                (source_left + line["right"] / prepared.width * source_crop_width)
                                / source_width,
                                6,
                            ),
                            round(
                                (source_top + line["bottom"] / prepared.height * source_crop_height)
                                / source_height,
                                6,
                            ),
                        ]
                        confidence = min(max(float(line["confidence"]), 0.0), 1.0)
                        marker = {
                            "kind": kind,
                            "matched_phrase": phrase,
                            "recognized_text": str(line["text"])[:160],
                            "ocr_confidence": round(confidence, 6),
                            "source_view": view.name,
                            "normalized_box": normalized_box,
                            "semantics": "VISIBLE_REVIEW_SIGNAL_CAN_BE_FORGED_OR_MISREAD",
                        }
                        key = (kind, phrase)
                        existing = markers.get(key)
                        if existing is None or confidence > float(existing["ocr_confidence"]):
                            markers[key] = marker

        if not successful_views:
            return VisibleMarkerEvidence(
                provider=self.name,
                available=True,
                checked=False,
                classification="VISIBLE_MARKER_ANALYSIS_FAILED",
                supports_ai_origin_review=False,
                reason_codes=("ALL_VISIBLE_MARKER_VIEWS_FAILED", *errors),
                limitations=("A failed visible-marker check is not a negative result.",),
            )

        found = tuple(markers.values())
        if found:
            best_confidence = max(float(item["ocr_confidence"]) for item in found)
            explicit = any(item["kind"] == "EXPLICIT_AI_LABEL" for item in found)
            marker_strength = min(0.98, (0.76 if explicit else 0.62) + 0.22 * best_confidence)
            return VisibleMarkerEvidence(
                provider=self.name,
                available=True,
                checked=True,
                classification="VISIBLE_AI_MARKER_FOUND",
                supports_ai_origin_review=True,
                marker_strength=round(marker_strength, 6),
                markers=found,
                reason_codes=(
                    "EXPLICIT_VISIBLE_AI_LABEL_FOUND"
                    if explicit
                    else "CONFIGURED_GENERATOR_MARK_FOUND",
                    "VISIBLE_MARKER_REQUIRES_REVIEW_NOT_AUTOMATIC_PROVENANCE",
                ),
                limitations=(
                    "Visible labels can be forged, copied, removed, or misread by OCR.",
                    "Absence of a recognized label is not evidence of human origin.",
                ),
            )

        return VisibleMarkerEvidence(
            provider=self.name,
            available=True,
            checked=True,
            classification="NO_VISIBLE_AI_MARKER_FOUND",
            supports_ai_origin_review=False,
            marker_strength=0.0,
            reason_codes=("NO_CONFIGURED_VISIBLE_AI_LABEL_RECOGNIZED",),
            limitations=("Absence of a recognized label is not evidence of human origin.",),
        )
