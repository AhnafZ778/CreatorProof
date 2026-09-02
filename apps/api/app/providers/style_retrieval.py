"""Creator-profile style descriptors.

Optional CSD ViT-L adapter plus a diagnostic fallback (palette, edges, texture).
The fallback sets learned=false and cannot attribute a creator. CSD is
experimental: the upstream checkpoint warning is surfaced, not hidden.
"""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import subprocess
import sys
import threading
from pathlib import Path

import numpy as np
from PIL import Image

from app.providers.remote_embeddings import RemoteHTTPEmbeddingProvider
from app.providers.style_signature import DiagnosticStyleEmbeddingProvider


class StyleProviderUnavailable(RuntimeError):
    pass


class RemoteCSDStyleEmbeddingProvider(RemoteHTTPEmbeddingProvider):
    """Identity-pinned CSD style inference hosted outside the API process."""

    name = "csd-vit-l-remote-http"
    learned = True
    upstream = "https://github.com/learn2phoenix/CSD"
    checkpoint_status = "UPSTREAM_WEIGHTS_DISCREPANCY_UNDER_INVESTIGATION"
    model_identity = "CSD_VIT_L_EXTERNAL_CHECKPOINT"
    preprocessing_identity = "UPSTREAM_CSD_TRANSFORMS_BRANCH0"
    dimensions = 768

    def __init__(
        self,
        *,
        endpoint_url: str,
        auth_token: str,
        expected_sha256: str,
        timeout_seconds: float = 30.0,
        max_attempts: int = 2,
        retry_backoff_seconds: float = 0.25,
        batch_size: int = 1,
        client=None,
        sleep=None,
    ) -> None:
        kwargs = {}
        if sleep is not None:
            kwargs["sleep"] = sleep
        super().__init__(
            name=self.name,
            lane="STYLE",
            endpoint_url=endpoint_url,
            auth_token=auth_token,
            model_identity=self.model_identity,
            preprocessing_identity=self.preprocessing_identity,
            expected_artifact_sha256=expected_sha256,
            dimensions=self.dimensions,
            timeout_seconds=timeout_seconds,
            max_attempts=max_attempts,
            retry_backoff_seconds=retry_backoff_seconds,
            batch_size=batch_size,
            client=client,
            **kwargs,
        )

    def status(self) -> dict:
        return {
            **super().status(),
            "checkpoint_status": self.checkpoint_status,
            "upstream": self.upstream,
            "repo_path": None,
            "model_path": None,
            "expected_repo_revision": None,
            "actual_repo_revision": None,
            "artifact_identity_state": (
                "REMOTE_IDENTITY_PINNED" if self.available else "INTEGRITY_REQUIREMENTS_NOT_MET"
            ),
        }


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
    model_identity = "CSD_VIT_L_EXTERNAL_CHECKPOINT"
    preprocessing_identity = "UPSTREAM_CSD_TRANSFORMS_BRANCH0"
    dimensions = 768

    def __init__(
        self,
        repo_path: Path,
        model_path: Path,
        device: str = "auto",
        *,
        allow_legacy_pickle: bool = False,
        expected_sha256: str = "",
        expected_repo_revision: str = "",
    ) -> None:
        self.repo_path = repo_path
        self.model_path = model_path
        self.requested_device = device
        self.allow_legacy_pickle = allow_legacy_pickle
        self.expected_sha256 = expected_sha256.strip().lower()
        self.expected_repo_revision = expected_repo_revision.strip().lower()
        self._torch = None
        self._model = None
        self._preprocess = None
        self._device = "cpu"
        self._load_error: str | None = None
        self._artifact_sha256: str | None = None
        self._repo_revision: str | None = None
        self._load_lock = threading.Lock()

    def _actual_checkpoint_sha256(self) -> str:
        if self._artifact_sha256 is not None:
            return self._artifact_sha256
        digest = hashlib.sha256()
        with self.model_path.open("rb") as source:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(block)
        self._artifact_sha256 = digest.hexdigest()
        return self._artifact_sha256

    def _checkpoint_integrity_reason(self) -> str | None:
        if not self.expected_sha256:
            return "CSD_CHECKPOINT_EXPECTED_SHA256_REQUIRED"
        if len(self.expected_sha256) != 64 or any(
            character not in "0123456789abcdef" for character in self.expected_sha256
        ):
            return "CSD_EXPECTED_SHA256_INVALID"
        if self._actual_checkpoint_sha256() != self.expected_sha256:
            return "CSD_CHECKPOINT_SHA256_MISMATCH"
        return None

    def _actual_repo_revision(self) -> str | None:
        if self._repo_revision is not None:
            return self._repo_revision
        try:
            completed = subprocess.run(
                ["git", "-C", str(self.repo_path), "rev-parse", "HEAD"],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        if completed.returncode != 0:
            return None
        revision = completed.stdout.strip().lower()
        if len(revision) != 40 or any(
            character not in "0123456789abcdef" for character in revision
        ):
            return None
        self._repo_revision = revision
        return revision

    def _repo_integrity_reason(self) -> str | None:
        if not self.expected_repo_revision:
            return None
        if len(self.expected_repo_revision) != 40 or any(
            character not in "0123456789abcdef" for character in self.expected_repo_revision
        ):
            return "CSD_EXPECTED_REPO_REVISION_INVALID"
        if self._actual_repo_revision() != self.expected_repo_revision:
            return "CSD_REPO_REVISION_MISMATCH"
        return None

    def _integrity_reason(self) -> str | None:
        if not self.model_path.is_file():
            return None
        return self._checkpoint_integrity_reason() or self._repo_integrity_reason()

    def _verify_module_origin(self, module) -> None:
        module_path = Path(str(getattr(module, "__file__", ""))).resolve()
        expected_root = (self.repo_path / "CSD").resolve()
        if not module_path.is_relative_to(expected_root):
            raise StyleProviderUnavailable("CSD_IMPORTED_MODULE_ORIGIN_MISMATCH")

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
        return importlib.util.find_spec("torch") is not None and self._integrity_reason() is None

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
        return self._integrity_reason()

    def status(self) -> dict:
        return {
            "provider": self.name,
            "available": self.available,
            "learned": True,
            "device": self.device,
            "reason": self.unavailable_reason,
            "checkpoint_status": self.checkpoint_status,
            "upstream": self.upstream,
            "repo_path": str(self.repo_path),
            "model_path": str(self.model_path),
            "model_identity": self.model_identity,
            "preprocessing_identity": self.preprocessing_identity,
            "expected_artifact_sha256": self.expected_sha256 or None,
            "actual_artifact_sha256": (
                self._actual_checkpoint_sha256() if self.model_path.is_file() else None
            ),
            "expected_repo_revision": self.expected_repo_revision or None,
            "actual_repo_revision": self._actual_repo_revision(),
            "artifact_identity_state": (
                "ARTIFACT_AND_SOURCE_VERIFIED"
                if self.available
                else "INTEGRITY_REQUIREMENTS_NOT_MET"
            ),
        }

    def _ensure_loaded(self):
        if self._model is not None:
            return self._torch, self._model, self._preprocess
        with self._load_lock:
            if self._model is not None:
                return self._torch, self._model, self._preprocess
            if not self.available:
                raise StyleProviderUnavailable(self.unavailable_reason or "CSD_UNAVAILABLE")

            try:
                import torch

                # Hash and source identity are verified before either deserialization path.
                integrity_reason = self._integrity_reason()
                if integrity_reason is not None:
                    raise StyleProviderUnavailable(integrity_reason)
                repo = str(self.repo_path.resolve())
                if repo not in sys.path:
                    sys.path.insert(0, repo)
                model_module = importlib.import_module("CSD.model")
                utils_module = importlib.import_module("CSD.utils")
                loss_module = importlib.import_module("CSD.loss_utils")
                for module in (model_module, utils_module, loss_module):
                    self._verify_module_origin(module)

                device = (
                    "cuda"
                    if self.requested_device == "auto" and torch.cuda.is_available()
                    else "cpu"
                    if self.requested_device == "auto"
                    else self.requested_device
                )
                model = model_module.CSD_CLIP("vit_large", "default")
                try:
                    checkpoint = torch.load(
                        str(self.model_path), map_location="cpu", weights_only=True
                    )
                except Exception as safe_load_error:
                    if not self.allow_legacy_pickle:
                        raise StyleProviderUnavailable(
                            "CSD_SAFE_CHECKPOINT_LOAD_FAILED_LEGACY_PICKLE_DISABLED"
                        ) from safe_load_error
                    checkpoint = torch.load(
                        str(self.model_path), map_location="cpu", weights_only=False
                    )
                if not isinstance(checkpoint, dict) or not isinstance(
                    checkpoint.get("model_state_dict"), dict
                ):
                    raise StyleProviderUnavailable("CSD_CHECKPOINT_STRUCTURE_INVALID")
                state_dict = utils_module.convert_state_dict(checkpoint["model_state_dict"])
                model.load_state_dict(state_dict, strict=True)
                model.eval().to(device)

                self._torch = torch
                self._model = model
                self._preprocess = loss_module.transforms_branch0
                self._device = device
                return torch, model, self._preprocess
            except StyleProviderUnavailable as exc:
                self._load_error = str(exc)
                raise
            except Exception as exc:
                self._load_error = f"CSD_LOAD_FAILED:{type(exc).__name__}"
                raise StyleProviderUnavailable(self._load_error) from exc

    def embed(self, image: Image.Image) -> np.ndarray:
        return self.embed_many([image])[0]

    def embed_many(self, images: list[Image.Image]) -> list[np.ndarray]:
        if not images:
            return []
        torch, model, preprocess = self._ensure_loaded()
        tensor = torch.stack([preprocess(image.convert("RGB")) for image in images]).to(
            self._device
        )
        with torch.inference_mode():
            output = model(tensor)
        if not isinstance(output, (tuple, list)) or len(output) < 3:
            raise RuntimeError("CSD model returned an unexpected output structure")
        matrix = output[2].detach().float().cpu().numpy()
        if matrix.shape[0] != len(images):
            raise RuntimeError("CSD batch result count is invalid")
        vectors: list[np.ndarray] = []
        for row in matrix:
            vector = row.reshape(-1).astype(np.float32)
            norm = float(np.linalg.norm(vector))
            if not np.isfinite(vector).all() or norm <= 1e-12:
                raise RuntimeError("CSD produced an invalid style descriptor")
            vectors.append(vector / norm)
        return vectors

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
        expected_repo_revision: str = "",
        remote_url: str = "",
        remote_auth_token: str = "",
        remote_timeout_seconds: float = 30.0,
        remote_max_attempts: int = 2,
        remote_retry_backoff_seconds: float = 0.25,
        remote_batch_size: int = 1,
    ) -> None:
        self.mode = mode
        self.local_primary = CSDStyleEmbeddingProvider(
            csd_repo_path,
            csd_model_path,
            device,
            allow_legacy_pickle=allow_legacy_pickle,
            expected_sha256=expected_sha256,
            expected_repo_revision=expected_repo_revision,
        )
        self.remote_primary = RemoteCSDStyleEmbeddingProvider(
            endpoint_url=remote_url,
            auth_token=remote_auth_token,
            expected_sha256=expected_sha256,
            timeout_seconds=remote_timeout_seconds,
            max_attempts=remote_max_attempts,
            retry_backoff_seconds=remote_retry_backoff_seconds,
            batch_size=remote_batch_size,
        )
        self.primary = self.remote_primary if mode == "remote" else self.local_primary
        self.fallback = DiagnosticStyleEmbeddingProvider()
        self._primary_failed_reason: str | None = None

    @property
    def _use_primary(self) -> bool:
        return (
            self.mode in {"auto", "csd", "remote"}
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
        primary_status = self.primary.status()
        return {
            "provider": self.name,
            "available": True,
            "learned": self.learned,
            "device": self.device,
            "reason": self.fallback_reason,
            "requested_provider": self.mode,
            "primary_provider": self.primary.name,
            "primary_checkpoint_status": getattr(self.primary, "checkpoint_status", None),
            "primary_identity": {
                "model_identity": primary_status["model_identity"],
                "preprocessing_identity": primary_status["preprocessing_identity"],
                "model_path": primary_status.get("model_path"),
                "endpoint_url": primary_status.get("endpoint_url"),
                "expected_artifact_sha256": primary_status.get("expected_artifact_sha256"),
                "actual_artifact_sha256": primary_status.get("actual_artifact_sha256"),
                "expected_repo_revision": primary_status.get("expected_repo_revision"),
                "actual_repo_revision": primary_status.get("actual_repo_revision"),
                "artifact_identity_state": primary_status.get("artifact_identity_state"),
            },
        }

    def embed(self, image: Image.Image) -> np.ndarray:
        if self._use_primary:
            try:
                return self.primary.embed(image)
            except Exception as exc:
                prefix = (
                    "CSD_REMOTE_RUNTIME_FALLBACK"
                    if self.mode == "remote"
                    else "CSD_RUNTIME_FALLBACK"
                )
                self._primary_failed_reason = f"{prefix}:{type(exc).__name__}"
        return self.fallback.embed(image)

    def embed_many(self, images: list[Image.Image]) -> list[np.ndarray]:
        if self._use_primary:
            try:
                return self.primary.embed_many(images)
            except Exception as exc:
                prefix = (
                    "CSD_REMOTE_RUNTIME_FALLBACK"
                    if self.mode == "remote"
                    else "CSD_RUNTIME_FALLBACK"
                )
                self._primary_failed_reason = f"{prefix}:{type(exc).__name__}"
        return self.fallback.embed_many(images)

    def force_fallback(self, reason: str) -> None:
        self._primary_failed_reason = reason

    def similarity(self, left: np.ndarray, right: np.ndarray) -> float:
        return self.active.similarity(left, right)
