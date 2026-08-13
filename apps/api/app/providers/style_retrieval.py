from __future__ import annotations

import hashlib
import importlib
import importlib.util
import sys
from pathlib import Path

import numpy as np
from PIL import Image

from app.providers.style_signature import DiagnosticStyleEmbeddingProvider


class StyleProviderUnavailable(RuntimeError):
    pass


class CSDStyleEmbeddingProvider:
    """Optional adapter around the upstream Contrastive Style Descriptors repository.

    CreatorProof does not vendor CSD source or weights. A user can place a checkout and checkpoint
    at the configured paths; this adapter follows the upstream public inference API. The provider
    remains EXPERIMENTAL because the upstream repository currently flags a weights discrepancy.
    """

    name = "csd-vit-l-experimental"
    learned = True
    upstream = "https://github.com/learn2phoenix/CSD"
    checkpoint_status = "UPSTREAM_WEIGHTS_DISCREPANCY_UNDER_INVESTIGATION"

    def __init__(
        self,
        repo_path: Path,
        model_path: Path,
        device: str = "auto",
        *,
        allow_legacy_pickle: bool = False,
        expected_sha256: str = "",
    ) -> None:
        self.repo_path = repo_path
        self.model_path = model_path
        self.requested_device = device
        self.allow_legacy_pickle = allow_legacy_pickle
        self.expected_sha256 = expected_sha256.strip().lower()
        self._torch = None
        self._model = None
        self._preprocess = None
        self._device = "cpu"
        self._load_error: str | None = None

    def _verified_checkpoint_sha256(self) -> str:
        digest = hashlib.sha256()
        with self.model_path.open("rb") as source:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(block)
        actual = digest.hexdigest()
        if not self.expected_sha256:
            raise StyleProviderUnavailable("CSD_LEGACY_PICKLE_REQUIRES_EXPECTED_SHA256")
        if len(self.expected_sha256) != 64 or any(
            character not in "0123456789abcdef" for character in self.expected_sha256
        ):
            raise StyleProviderUnavailable("CSD_EXPECTED_SHA256_INVALID")
        if actual != self.expected_sha256:
            raise StyleProviderUnavailable("CSD_CHECKPOINT_SHA256_MISMATCH")
        return actual

    @property
    def device(self) -> str:
        return self._device

    @property
    def available(self) -> bool:
        if self._load_error is not None:
            return False
        if not (self.repo_path / "CSD" / "model.py").is_file():
            return False
        if not self.model_path.is_file():
            return False
        return importlib.util.find_spec("torch") is not None

    @property
    def unavailable_reason(self) -> str | None:
        if self._load_error:
            return self._load_error
        if not (self.repo_path / "CSD" / "model.py").is_file():
            return f"CSD_REPO_MISSING:{self.repo_path}"
        if not self.model_path.is_file():
            return f"CSD_MODEL_MISSING:{self.model_path}"
        if importlib.util.find_spec("torch") is None:
            return "PYTORCH_NOT_INSTALLED"
        return None

    def status(self) -> dict:
        return {
            "provider": self.name,
            "available": self.available,
            "learned": True,
            "device": self.device,
            "reason": self.unavailable_reason,
            "checkpoint_status": self.checkpoint_status,
            "upstream": self.upstream,
        }

    def _ensure_loaded(self):
        if self._model is not None:
            return self._torch, self._model, self._preprocess
        if not self.available:
            raise StyleProviderUnavailable(self.unavailable_reason or "CSD_UNAVAILABLE")

        try:
            import torch

            repo = str(self.repo_path.resolve())
            if repo not in sys.path:
                sys.path.insert(0, repo)
            model_module = importlib.import_module("CSD.model")
            utils_module = importlib.import_module("CSD.utils")
            loss_module = importlib.import_module("CSD.loss_utils")

            device = (
                "cuda"
                if self.requested_device == "auto" and torch.cuda.is_available()
                else "cpu"
                if self.requested_device == "auto"
                else self.requested_device
            )
            model = model_module.CSD_CLIP("vit_large", "default")
            try:
                checkpoint = torch.load(str(self.model_path), map_location="cpu", weights_only=True)
            except Exception as safe_load_error:
                if not self.allow_legacy_pickle:
                    raise StyleProviderUnavailable(
                        "CSD_SAFE_CHECKPOINT_LOAD_FAILED_LEGACY_PICKLE_DISABLED"
                    ) from safe_load_error
                self._verified_checkpoint_sha256()
                checkpoint = torch.load(
                    str(self.model_path), map_location="cpu", weights_only=False
                )
            state_dict = utils_module.convert_state_dict(checkpoint["model_state_dict"])
            model.load_state_dict(state_dict, strict=False)
            model.eval().to(device)

            self._torch = torch
            self._model = model
            self._preprocess = loss_module.transforms_branch0
            self._device = device
            return torch, model, self._preprocess
        except Exception as exc:
            self._load_error = f"CSD_LOAD_FAILED:{type(exc).__name__}"
            raise StyleProviderUnavailable(self._load_error) from exc

    def embed(self, image: Image.Image) -> np.ndarray:
        torch, model, preprocess = self._ensure_loaded()
        tensor = preprocess(image.convert("RGB")).unsqueeze(0).to(self._device)
        with torch.inference_mode():
            output = model(tensor)
        if not isinstance(output, (tuple, list)) or len(output) < 3:
            raise RuntimeError("CSD model returned an unexpected output structure")
        vector = output[2][0].detach().float().cpu().numpy().reshape(-1).astype(np.float32)
        norm = float(np.linalg.norm(vector))
        if not np.isfinite(vector).all() or norm <= 1e-12:
            raise RuntimeError("CSD produced an invalid style descriptor")
        return vector / norm

    @staticmethod
    def similarity(left: np.ndarray, right: np.ndarray) -> float:
        if left.shape != right.shape or left.ndim != 1:
            raise ValueError("Embedding shapes do not match")
        return float(np.clip(np.dot(left, right), -1.0, 1.0))


class StyleEmbeddingRouter:
    """Fail-visible style provider router.

    `auto` uses CSD only when the external runtime is present and loadable. Any runtime failure
    switches this process to the transparent diagnostic descriptor. The Evidence Packet records
    that fallback so a deterministic diagnostic score can never masquerade as learned AI.
    """

    def __init__(
        self,
        *,
        mode: str,
        csd_repo_path: Path,
        csd_model_path: Path,
        device: str,
        allow_legacy_pickle: bool = False,
        expected_sha256: str = "",
    ) -> None:
        self.mode = mode
        self.primary = CSDStyleEmbeddingProvider(
            csd_repo_path,
            csd_model_path,
            device,
            allow_legacy_pickle=allow_legacy_pickle,
            expected_sha256=expected_sha256,
        )
        self.fallback = DiagnosticStyleEmbeddingProvider()
        self._primary_failed_reason: str | None = None

    @property
    def _use_primary(self) -> bool:
        return (
            self.mode in {"auto", "csd"}
            and self._primary_failed_reason is None
            and self.primary.available
        )

    @property
    def active(self):
        return self.primary if self._use_primary else self.fallback

    @property
    def name(self) -> str:
        return self.active.name

    @property
    def learned(self) -> bool:
        return bool(self.active.learned)

    @property
    def available(self) -> bool:
        return True

    @property
    def device(self) -> str:
        return self.active.device

    @property
    def fallback_reason(self) -> str | None:
        if self.learned:
            return None
        if self.mode == "diagnostic":
            return "STYLE_PROVIDER_CONFIGURED_DIAGNOSTIC"
        return self._primary_failed_reason or self.primary.unavailable_reason

    def status(self) -> dict:
        return {
            "provider": self.name,
            "available": True,
            "learned": self.learned,
            "device": self.device,
            "reason": self.fallback_reason,
            "requested_provider": self.mode,
            "primary_provider": self.primary.name,
            "primary_checkpoint_status": self.primary.checkpoint_status,
        }

    def embed(self, image: Image.Image) -> np.ndarray:
        if self._use_primary:
            try:
                return self.primary.embed(image)
            except Exception as exc:
                self._primary_failed_reason = f"CSD_RUNTIME_FALLBACK:{type(exc).__name__}"
        return self.fallback.embed(image)

    def force_fallback(self, reason: str) -> None:
        self._primary_failed_reason = reason

    def similarity(self, left: np.ndarray, right: np.ndarray) -> float:
        return self.active.similarity(left, right)
