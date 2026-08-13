from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
from PIL import Image


class AIProviderUnavailable(RuntimeError):
    pass


class SSCDVisualEmbeddingProvider:
    """TorchScript SSCD image-copy descriptor provider.

    The model artifact is intentionally external to the source archive. The official SSCD
    project publishes a standalone TorchScript model; CreatorProof loads that pinned local
    artifact when present and otherwise reports an explicit baseline fallback.
    """

    name = "sscd-disc-mixup-torchscript"
    model_identity = "SSCD_DISC_MIXUP_TORCHSCRIPT_LOCAL_ARTIFACT"
    preprocessing_identity = "SSCD_RGB_SHORTEST_SIDE_288_IMAGENET_NORMALIZATION_V1"
    dimensions = 512

    def __init__(self, model_path: Path, device: str = "auto") -> None:
        self.model_path = model_path
        self.requested_device = device
        self._torch = None
        self._model = None
        self._device = "cpu"
        self._load_error: str | None = None

    @property
    def available(self) -> bool:
        if not self.model_path.is_file():
            return False
        if importlib.util.find_spec("torch") is None:
            return False
        return self._load_error is None

    @property
    def unavailable_reason(self) -> str | None:
        if not self.model_path.is_file():
            return f"SSCD_MODEL_MISSING:{self.model_path}"
        if importlib.util.find_spec("torch") is None:
            return "PYTORCH_NOT_INSTALLED"
        return self._load_error

    @property
    def device(self) -> str:
        return self._device

    def status(self) -> dict:
        return {
            "provider": self.name,
            "available": self.available,
            "model_path": str(self.model_path),
            "device": self.device,
            "reason": self.unavailable_reason,
        }

    def _ensure_loaded(self):
        if self._model is not None:
            return self._torch, self._model
        if not self.available:
            raise AIProviderUnavailable(self.unavailable_reason or "SSCD_UNAVAILABLE")

        import torch

        if self.requested_device == "auto":
            device = "cuda" if torch.cuda.is_available() else "cpu"
        else:
            device = self.requested_device
        try:
            model = torch.jit.load(str(self.model_path), map_location=device)
            model.eval()
        except Exception as exc:
            self._load_error = f"SSCD_LOAD_FAILED:{type(exc).__name__}"
            raise AIProviderUnavailable(self._load_error) from exc
        self._torch = torch
        self._model = model
        self._device = device
        return torch, model

    @staticmethod
    def _preprocess(image: Image.Image) -> np.ndarray:
        rgb = image.convert("RGB")
        width, height = rgb.size
        shortest = max(min(width, height), 1)
        scale = 288.0 / shortest
        resized = rgb.resize(
            (max(1, round(width * scale)), max(1, round(height * scale))),
            Image.Resampling.BILINEAR,
        )
        array = np.asarray(resized, dtype=np.float32) / 255.0
        mean = np.asarray([0.485, 0.456, 0.406], dtype=np.float32)
        std = np.asarray([0.229, 0.224, 0.225], dtype=np.float32)
        array = (array - mean) / std
        return np.transpose(array, (2, 0, 1))[None, ...].copy()

    def embed(self, image: Image.Image) -> np.ndarray:
        torch, model = self._ensure_loaded()
        batch = torch.from_numpy(self._preprocess(image)).to(self._device)
        with torch.inference_mode():
            output = model(batch)
        vector = output[0].detach().float().cpu().numpy().reshape(-1).astype(np.float32)
        norm = float(np.linalg.norm(vector))
        if not np.isfinite(vector).all() or norm <= 1e-12:
            raise RuntimeError("SSCD produced an invalid descriptor")
        return vector / norm

    @staticmethod
    def similarity(left: np.ndarray, right: np.ndarray) -> float:
        if left.shape != right.shape or left.ndim != 1:
            raise ValueError("Embedding shapes do not match")
        return float(np.clip(np.dot(left, right), -1.0, 1.0))
