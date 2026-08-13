from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np
from PIL import Image

FACTOR_ORDER = ("palette", "tone", "stroke_orientation", "texture")


def _l1_histogram(values: np.ndarray, bins: int, value_range: tuple[float, float]) -> np.ndarray:
    histogram, _ = np.histogram(values.reshape(-1), bins=bins, range=value_range)
    result = histogram.astype(np.float32)
    total = float(result.sum())
    return result / total if total > 0 else result


def _normalized(vector: np.ndarray) -> np.ndarray:
    vector = np.asarray(vector, dtype=np.float32).reshape(-1)
    norm = float(np.linalg.norm(vector))
    return vector / norm if norm > 1e-12 else vector


def _histogram_intersection(left: np.ndarray, right: np.ndarray) -> float:
    if left.shape != right.shape:
        raise ValueError("Style factor shapes do not match")
    return float(np.clip(np.minimum(left, right).sum(), 0.0, 1.0))


@dataclass(frozen=True, slots=True)
class StyleSignature:
    palette: np.ndarray
    tone: np.ndarray
    stroke_orientation: np.ndarray
    texture: np.ndarray

    def vector(self) -> np.ndarray:
        # Each family contributes equally to the diagnostic embedding irrespective of
        # histogram dimensionality. This is an explainability baseline, not a learned model.
        families = [
            _normalized(self.palette),
            _normalized(self.tone),
            _normalized(self.stroke_orientation),
            _normalized(self.texture),
        ]
        return _normalized(np.concatenate([family * 0.5 for family in families]))


class DiagnosticStyleEmbeddingProvider:
    """Content-agnostic-ish visual-style diagnostics with no learned weights.

    The descriptor deliberately exposes its factors. It is useful as a transparent fallback
    and UI explanation layer, but it must never be represented as an artist-attribution model.
    """

    name = "diagnostic-style-signature-v1"
    model_identity = "CREATORPROOF_DIAGNOSTIC_STYLE_SIGNATURE_V1"
    preprocessing_identity = "PALETTE_TONE_EDGE_TEXTURE_256_V1"
    dimensions = 236
    learned = False
    device = "cpu"

    @property
    def available(self) -> bool:
        return True

    @property
    def unavailable_reason(self) -> None:
        return None

    def status(self) -> dict:
        return {
            "provider": self.name,
            "available": True,
            "learned": False,
            "device": self.device,
            "reason": None,
        }

    def embed(self, image: Image.Image) -> np.ndarray:
        return style_signature(image).vector()

    def embed_many(self, images: list[Image.Image]) -> list[np.ndarray]:
        return [self.embed(image) for image in images]

    @staticmethod
    def similarity(left: np.ndarray, right: np.ndarray) -> float:
        if left.shape != right.shape or left.ndim != 1:
            raise ValueError("Embedding shapes do not match")
        return float(np.clip(np.dot(left, right), -1.0, 1.0))


def style_signature(image: Image.Image) -> StyleSignature:
    rgb = np.asarray(image.convert("RGB").resize((256, 256), Image.Resampling.LANCZOS))
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)

    # 3-D HSV color distribution: hue receives more resolution than saturation/value.
    palette, _ = np.histogramdd(
        hsv.reshape(-1, 3),
        bins=(12, 4, 4),
        range=((0, 180), (0, 256), (0, 256)),
    )
    palette = palette.astype(np.float32).reshape(-1)
    palette /= max(float(palette.sum()), 1.0)

    tone = _l1_histogram(gray, bins=16, value_range=(0, 256))

    gray_float = gray.astype(np.float32) / 255.0
    gradient_x = cv2.Sobel(gray_float, cv2.CV_32F, 1, 0, ksize=3)
    gradient_y = cv2.Sobel(gray_float, cv2.CV_32F, 0, 1, ksize=3)
    magnitude, angle = cv2.cartToPolar(gradient_x, gradient_y, angleInDegrees=True)
    orientation = np.mod(angle, 180.0)
    orientation_hist, _ = np.histogram(
        orientation.reshape(-1),
        bins=12,
        range=(0.0, 180.0),
        weights=magnitude.reshape(-1),
    )
    orientation_hist = orientation_hist.astype(np.float32)
    orientation_hist /= max(float(orientation_hist.sum()), 1e-12)

    # Rotation-unaware 8-neighbour LBP compressed into 16 bins. It gives a cheap, transparent
    # texture statistic without pretending that the tiles identify semantic objects.
    center = gray[1:-1, 1:-1]
    neighbours = (
        gray[:-2, :-2],
        gray[:-2, 1:-1],
        gray[:-2, 2:],
        gray[1:-1, 2:],
        gray[2:, 2:],
        gray[2:, 1:-1],
        gray[2:, :-2],
        gray[1:-1, :-2],
    )
    lbp = np.zeros(center.shape, dtype=np.uint8)
    for bit, neighbour in enumerate(neighbours):
        lbp |= (neighbour >= center).astype(np.uint8) << bit
    texture = _l1_histogram(lbp, bins=16, value_range=(0, 256))

    return StyleSignature(
        palette=palette,
        tone=tone,
        stroke_orientation=orientation_hist,
        texture=texture,
    )


def compare_signatures(left: StyleSignature, right: StyleSignature) -> dict[str, float]:
    factors = {
        "palette": _histogram_intersection(left.palette, right.palette),
        "tone": _histogram_intersection(left.tone, right.tone),
        "stroke_orientation": _histogram_intersection(
            left.stroke_orientation, right.stroke_orientation
        ),
        "texture": _histogram_intersection(left.texture, right.texture),
    }
    factors["diagnostic_similarity"] = float(np.mean([factors[name] for name in FACTOR_ORDER]))
    return {name: round(value, 6) for name, value in factors.items()}


def dominant_palette(image: Image.Image, colors: int = 6) -> list[dict[str, float | str]]:
    sample = image.convert("RGB").resize((160, 160), Image.Resampling.LANCZOS)
    quantized = sample.quantize(colors=colors, method=Image.Quantize.MEDIANCUT)
    raw_palette = quantized.getpalette() or []
    counts = sorted(quantized.getcolors(maxcolors=colors) or [], reverse=True)
    total = max(sum(count for count, _ in counts), 1)
    result: list[dict[str, float | str]] = []
    for count, index in counts:
        offset = index * 3
        if offset + 2 >= len(raw_palette):
            continue
        red, green, blue = raw_palette[offset : offset + 3]
        result.append(
            {
                "hex": f"#{red:02x}{green:02x}{blue:02x}",
                "share": round(count / total, 6),
            }
        )
    return result


def _tiles(image: Image.Image, grid_size: int) -> list[tuple[int, int, StyleSignature]]:
    width, height = image.size
    tiles: list[tuple[int, int, StyleSignature]] = []
    for row in range(grid_size):
        for column in range(grid_size):
            left = round(column * width / grid_size)
            upper = round(row * height / grid_size)
            right = round((column + 1) * width / grid_size)
            lower = round((row + 1) * height / grid_size)
            crop = image.crop((left, upper, max(left + 1, right), max(upper + 1, lower)))
            tiles.append((row, column, style_signature(crop)))
    return tiles


def cross_content_style_map(
    query: Image.Image,
    reference: Image.Image,
    *,
    grid_size: int = 4,
) -> dict:
    query_tiles = _tiles(query, grid_size)
    reference_tiles = _tiles(reference, grid_size)

    pair_scores: dict[tuple[int, int], dict[str, float]] = {}
    for query_index, (_, _, query_signature) in enumerate(query_tiles):
        for reference_index, (_, _, reference_signature) in enumerate(reference_tiles):
            pair_scores[(query_index, reference_index)] = compare_signatures(
                query_signature, reference_signature
            )

    def best_cells(source: str) -> list[dict]:
        source_tiles = query_tiles if source == "query" else reference_tiles
        target_tiles = reference_tiles if source == "query" else query_tiles
        cells: list[dict] = []
        for source_index, (row, column, _) in enumerate(source_tiles):
            candidates: list[tuple[float, int, dict[str, float]]] = []
            for target_index in range(len(target_tiles)):
                key = (
                    (source_index, target_index)
                    if source == "query"
                    else (target_index, source_index)
                )
                factors = pair_scores[key]
                candidates.append((factors["diagnostic_similarity"], target_index, factors))
            score, target_index, factors = max(candidates, key=lambda item: (item[0], -item[1]))
            target_row, target_column, _ = target_tiles[target_index]
            cells.append(
                {
                    "id": f"{source}-tile-{row}-{column}",
                    "row": row,
                    "column": column,
                    "score": round(score, 6),
                    "best_partner": {"row": target_row, "column": target_column},
                    "factors": factors,
                }
            )
        return cells

    return {
        "grid_size": grid_size,
        "query_cells": best_cells("query"),
        "reference_cells": best_cells("reference"),
        "semantics": "CROSS_CONTENT_STYLE_DIAGNOSTIC_NOT_PIXEL_CORRESPONDENCE",
    }


def explain_style_pair(query: Image.Image, reference: Image.Image) -> dict:
    query_signature = style_signature(query)
    reference_signature = style_signature(reference)
    return {
        "query_size": [query.width, query.height],
        "reference_size": [reference.width, reference.height],
        "factors": compare_signatures(query_signature, reference_signature),
        "query_palette": dominant_palette(query),
        "reference_palette": dominant_palette(reference),
        "tile_map": cross_content_style_map(query, reference),
        "factor_semantics": {
            "palette": "Similarity of coarse HSV color distributions.",
            "tone": "Similarity of luminance distributions.",
            "stroke_orientation": (
                "Similarity of edge-direction energy; a proxy for mark/line structure."
            ),
            "texture": "Similarity of local binary-pattern texture distributions.",
        },
        "warning": (
            "These transparent factors explain low-level visual appearance only. They are not "
            "semantic segmentation, artist attribution, or calibrated infringement probabilities."
        ),
    }
