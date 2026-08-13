from __future__ import annotations

import hashlib
import json
import math
import shlex
import shutil
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from io import BytesIO
from pathlib import Path
from typing import Any

import httpx
import numpy as np
from PIL import Image, ImageOps

from app.providers.contracts import SyntheticDetectorScore


def _sigmoid(value: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(min(float(value), 50.0), -50.0)))


def _logit(value: float) -> float:
    clipped = min(max(float(value), 1e-6), 1.0 - 1e-6)
    return math.log(clipped / (1.0 - clipped))


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class SyntheticEvidenceFamilyRegistry:
    """Govern which detector lineages may count as independent evidence families."""

    schema = "creatorproof.synthetic_evidence_family_registry.v1"

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.entries: dict[str, dict] = {}
        self.state = "NOT_CONFIGURED"
        self.reason: str | None = None
        if not self.path.is_file():
            self.reason = "SYNTHETIC_EVIDENCE_FAMILY_REGISTRY_NOT_FOUND"
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if payload.get("schema") != self.schema:
                raise ValueError("unsupported schema")
            entries = payload.get("entries")
            if not isinstance(entries, list):
                raise ValueError("entries must be an array")
            lineage_to_family: dict[str, str] = {}
            for entry in entries:
                if not isinstance(entry, dict):
                    raise ValueError("registry entry must be an object")
                required = (
                    "provider",
                    "evidence_family",
                    "lineage_id",
                    "model_version",
                    "artifact_sha256",
                    "preprocessing_identity",
                    "review_state",
                )
                if any(not str(entry.get(field) or "").strip() for field in required):
                    raise ValueError("registry entry is incomplete")
                if entry["review_state"] != "APPROVED_FOR_FAMILY_COUNTING":
                    continue
                provider = str(entry["provider"])
                if provider in self.entries:
                    raise ValueError("provider entries must be unique")
                digest = str(entry["artifact_sha256"]).lower()
                if len(digest) != 64 or any(
                    character not in "0123456789abcdef" for character in digest
                ):
                    raise ValueError("artifact_sha256 must be a SHA-256 digest")
                executable_digest = entry.get("executable_sha256")
                if executable_digest is not None:
                    executable_digest = str(executable_digest).lower()
                    if len(executable_digest) != 64 or any(
                        character not in "0123456789abcdef" for character in executable_digest
                    ):
                        raise ValueError("executable_sha256 must be a SHA-256 digest")
                lineage_id = str(entry["lineage_id"])
                family = str(entry["evidence_family"])
                existing_family = lineage_to_family.get(lineage_id)
                if existing_family is not None and existing_family != family:
                    raise ValueError("one lineage cannot be assigned to multiple families")
                lineage_to_family[lineage_id] = family
                self.entries[provider] = {**entry, "artifact_sha256": digest}
            self.state = "READY" if self.entries else "NO_APPROVED_ENTRIES"
            if not self.entries:
                self.reason = "NO_EVIDENCE_FAMILY_ENTRY_APPROVED"
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            self.entries = {}
            self.state = "INVALID"
            self.reason = f"SYNTHETIC_EVIDENCE_FAMILY_REGISTRY_INVALID:{type(exc).__name__}"

    def govern(self, score: SyntheticDetectorScore, detector) -> SyntheticDetectorScore:
        entry = self.entries.get(score.provider)
        warnings = list(score.warnings)
        if entry is None:
            warnings.append("EVIDENCE_FAMILY_NOT_REGISTRY_APPROVED")
            return replace(score, evidence_family_verified=False, warnings=tuple(warnings))
        observed = {
            "model_version": score.model_version,
            "artifact_sha256": score.artifact_sha256,
            "preprocessing_identity": score.preprocessing_identity,
        }
        mismatches = [field for field, value in observed.items() if str(value) != str(entry[field])]
        expected_executable = entry.get("executable_sha256")
        if expected_executable:
            executable_path = getattr(detector, "executable_path", None)
            actual_executable = (
                _file_sha256(Path(executable_path))
                if executable_path and Path(executable_path).is_file()
                else None
            )
            if actual_executable != expected_executable:
                mismatches.append("executable_sha256")
        if mismatches:
            warnings.append("EVIDENCE_FAMILY_REGISTRY_IDENTITY_MISMATCH:" + ",".join(mismatches))
            return replace(score, evidence_family_verified=False, warnings=tuple(warnings))
        return replace(
            score,
            evidence_family=str(entry["evidence_family"]),
            evidence_family_verified=True,
            warnings=tuple(warnings),
        )

    def status(self) -> dict:
        return {
            "state": self.state,
            "reason": self.reason,
            "path": str(self.path),
            "approved_providers": sorted(self.entries),
            "approved_families": sorted(
                {str(entry["evidence_family"]) for entry in self.entries.values()}
            ),
        }


class SyntheticCalibrationRegistry:
    """Load held-out, provider-specific Platt calibration parameters.

    A calibration is accepted only when its manifest identifies the provider and
    records enough positive and negative examples. This prevents a tiny demo set
    from silently turning a detector logit into a probability-like product claim.
    """

    def __init__(
        self,
        path: Path,
        *,
        min_samples: int,
        min_class_samples: int,
        expected_domain_id: str = "",
        expected_crop_policy_id: str = "",
        expected_model_bundle_manifest_digest: str = "",
    ) -> None:
        self.path = Path(path)
        self.entries: dict[str, dict] = {}
        self.state = "NOT_CONFIGURED"
        self.reason: str | None = None
        self.expected_domain_id = expected_domain_id
        self.expected_crop_policy_id = expected_crop_policy_id
        self.expected_model_bundle_manifest_digest = expected_model_bundle_manifest_digest
        if not self.path.exists():
            self.reason = "SYNTHETIC_CALIBRATION_FILE_NOT_FOUND"
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if payload.get("schema") != "creatorproof.synthetic_calibration.v2":
                raise ValueError("unsupported schema")
            providers = payload.get("providers")
            if not isinstance(providers, dict):
                raise ValueError("providers must be an object")
            for provider, entry in providers.items():
                if not isinstance(entry, dict):
                    continue
                sample_count = int(entry.get("sample_count") or 0)
                positive_count = int(entry.get("positive_count") or 0)
                negative_count = int(entry.get("negative_count") or 0)
                slope = float(entry.get("slope"))
                intercept = float(entry.get("intercept"))
                required_identity_fields = (
                    "model_version",
                    "artifact_sha256",
                    "preprocessing_identity",
                    "domain_id",
                    "crop_policy_id",
                    "dataset_id",
                    "corpus_manifest_set_digest_sha256",
                    "model_bundle_manifest_digest_sha256",
                )
                identity_complete = all(
                    str(entry.get(field) or "").strip() for field in required_identity_fields
                )
                sha_fields_valid = all(
                    len(str(entry[field])) == 64
                    and all(character in "0123456789abcdef" for character in str(entry[field]))
                    for field in (
                        "artifact_sha256",
                        "corpus_manifest_set_digest_sha256",
                        "model_bundle_manifest_digest_sha256",
                    )
                    if entry.get(field)
                )
                adequate = (
                    sample_count >= min_samples
                    and positive_count >= min_class_samples
                    and negative_count >= min_class_samples
                    and slope > 0.0
                    and math.isfinite(slope)
                    and math.isfinite(intercept)
                    and identity_complete
                    and sha_fields_valid
                )
                if adequate:
                    self.entries[str(provider)] = entry
            self.state = "READY" if self.entries else "INSUFFICIENT_SUPPORT"
            if not self.entries:
                self.reason = "NO_PROVIDER_CALIBRATION_PASSED_SUPPORT_GATES"
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            self.state = "INVALID"
            self.reason = f"SYNTHETIC_CALIBRATION_INVALID:{type(exc).__name__}"

    def apply(
        self,
        provider: str,
        model_version: str | None,
        raw_score: float,
        artifact_sha256: str | None = None,
        preprocessing_identity: str | None = None,
    ) -> tuple[float, dict]:
        entry = self.entries.get(provider)
        if entry is None:
            return float(raw_score), {
                "applied": False,
                "state": "NOT_AVAILABLE_FOR_PROVIDER",
                "semantics": "RAW_DETECTOR_SCORE_NOT_PROBABILITY",
            }
        expected_version = entry.get("model_version")
        if expected_version and str(expected_version) != str(model_version):
            return float(raw_score), {
                "applied": False,
                "state": "MODEL_VERSION_MISMATCH",
                "semantics": "RAW_DETECTOR_SCORE_NOT_PROBABILITY",
            }
        context = {
            "domain_id": self.expected_domain_id or None,
            "crop_policy_id": self.expected_crop_policy_id or None,
            "artifact_sha256": artifact_sha256,
            "preprocessing_identity": preprocessing_identity,
            "model_bundle_manifest_digest_sha256": (
                self.expected_model_bundle_manifest_digest or None
            ),
        }
        mismatched = [
            key
            for key, current in context.items()
            if entry.get(key) and str(entry[key]) != str(current)
        ]
        if mismatched:
            return float(raw_score), {
                "applied": False,
                "state": "CALIBRATION_CONTEXT_MISMATCH",
                "mismatched_fields": mismatched,
                "semantics": "RAW_DETECTOR_SCORE_NOT_PROBABILITY",
            }
        calibrated = _sigmoid(float(entry["slope"]) * _logit(raw_score) + float(entry["intercept"]))
        return calibrated, {
            "applied": True,
            "state": "HELD_OUT_PLATT_CALIBRATION",
            "dataset_id": entry.get("dataset_id"),
            "sample_count": entry.get("sample_count"),
            "brier_score": entry.get("brier_score"),
            "expected_calibration_error": entry.get("expected_calibration_error"),
            "domain_id": entry.get("domain_id"),
            "crop_policy_id": entry.get("crop_policy_id"),
            "artifact_sha256": entry.get("artifact_sha256"),
            "preprocessing_identity": entry.get("preprocessing_identity"),
            "corpus_manifest_set_digest_sha256": entry.get("corpus_manifest_set_digest_sha256"),
            "model_bundle_manifest_digest_sha256": entry.get("model_bundle_manifest_digest_sha256"),
            "semantics": "CALIBRATED_ON_RECORDED_DOMAIN_NOT_UNIVERSAL_PROBABILITY",
        }

    def status(self) -> dict:
        return {
            "state": self.state,
            "providers": sorted(self.entries),
            "reason": self.reason,
            "expected_domain_id": self.expected_domain_id or None,
            "expected_crop_policy_id": self.expected_crop_policy_id or None,
            "expected_model_bundle_manifest_digest_sha256": (
                self.expected_model_bundle_manifest_digest or None
            ),
        }


def _device(requested: str, torch) -> str:
    if requested == "cpu":
        return "cpu"
    if requested == "cuda":
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA_REQUESTED_BUT_UNAVAILABLE")
        return "cuda"
    return "cuda" if torch.cuda.is_available() else "cpu"


def _imagenet_tensor(image: Image.Image, size: int, torch):
    fitted = ImageOps.fit(
        ImageOps.exif_transpose(image).convert("RGB"),
        (size, size),
        method=Image.Resampling.BICUBIC,
    )
    array = np.asarray(fitted, dtype=np.float32) / 255.0
    array = (array - np.asarray([0.485, 0.456, 0.406], dtype=np.float32)) / np.asarray(
        [0.229, 0.224, 0.225], dtype=np.float32
    )
    return torch.from_numpy(array.transpose(2, 0, 1)).unsqueeze(0)


def _community_forensics_crop(image: Image.Image) -> Image.Image:
    """Match the official Community Forensics 384px evaluation transform.

    The upstream evaluation pipeline resizes the shorter side to 440 with
    bilinear interpolation, then takes a 384px center crop. Directly force-fitting
    a non-square image to 384x384 changes the model input distribution and can
    produce severe false negatives.
    """

    rgb = ImageOps.exif_transpose(image).convert("RGB")
    width, height = rgb.size
    if width <= 0 or height <= 0:
        raise ValueError("IMAGE_HAS_INVALID_DIMENSIONS")
    resize_short_side = 440
    crop_size = 384
    if width < height:
        resized_size = (resize_short_side, round(height * resize_short_side / width))
    else:
        resized_size = (round(width * resize_short_side / height), resize_short_side)
    resized = rgb.resize(resized_size, Image.Resampling.BILINEAR)
    left = (resized.width - crop_size) // 2
    top = (resized.height - crop_size) // 2
    return resized.crop((left, top, left + crop_size, top + crop_size))


def _community_forensics_tensor(image: Image.Image, torch):
    cropped = _community_forensics_crop(image)
    array = np.asarray(cropped, dtype=np.float32) / 255.0
    array = (array - np.asarray([0.485, 0.456, 0.406], dtype=np.float32)) / np.asarray(
        [0.229, 0.224, 0.225], dtype=np.float32
    )
    return torch.from_numpy(array.transpose(2, 0, 1)).unsqueeze(0)


class CommunityForensicsDetector:
    """Clean integration for the MIT-licensed Community Forensics checkpoint.

    Model bytes stay outside the repository. The setup script downloads the official
    safetensors snapshot; pickle checkpoints are deliberately not loaded here.
    """

    name = "community-forensics-vit-small-384"
    evidence_family = "SEMANTIC_GENERATOR_GENERALIZATION"

    preprocessing_identity = "COMMUNITY_FORENSICS_SHORT_SIDE_440_CENTER_CROP_384_V1"

    def __init__(
        self,
        model_path: Path,
        requested_device: str = "auto",
        *,
        expected_sha256: str = "",
    ) -> None:
        self.model_path = Path(model_path)
        self.requested_device = requested_device
        self.expected_sha256 = expected_sha256.strip().lower()
        self.artifact_sha256: str | None = None
        self.available = False
        self.unavailable_reason: str | None = None
        self._model = None
        self._torch = None
        self._runtime_device = "unavailable"
        if not self.model_path.exists():
            self.unavailable_reason = "COMMUNITY_FORENSICS_MODEL_NOT_FOUND"
            return
        try:
            import timm  # type: ignore
            import torch  # type: ignore
            from safetensors.torch import load_file  # type: ignore

            weights = sorted(self.model_path.glob("*.safetensors"))
            if len(weights) != 1:
                self.unavailable_reason = "COMMUNITY_FORENSICS_SAFETENSORS_NOT_FOUND"
                return
            weights_path = weights[0]
            digest = hashlib.sha256()
            with weights_path.open("rb") as source:
                for block in iter(lambda: source.read(1024 * 1024), b""):
                    digest.update(block)
            self.artifact_sha256 = digest.hexdigest()
            if self.expected_sha256:
                if len(self.expected_sha256) != 64 or any(
                    character not in "0123456789abcdef" for character in self.expected_sha256
                ):
                    self.unavailable_reason = "COMMUNITY_FORENSICS_EXPECTED_SHA256_INVALID"
                    return
                if self.artifact_sha256 != self.expected_sha256:
                    self.unavailable_reason = "COMMUNITY_FORENSICS_SHA256_MISMATCH"
                    return
            runtime_device = _device(requested_device, torch)
            model = timm.create_model(
                "vit_small_patch16_384.augreg_in21k_ft_in1k",
                pretrained=False,
                num_classes=1,
            )
            state = load_file(str(weights_path), device="cpu")
            if state and all(key.startswith("vit.") for key in state):
                state = {key.removeprefix("vit."): value for key, value in state.items()}
            model.load_state_dict(state, strict=True)
            model.eval().to(runtime_device)
            self._model = model
            self._torch = torch
            self._runtime_device = runtime_device
            self.available = True
        except Exception as exc:
            self.unavailable_reason = f"COMMUNITY_FORENSICS_LOAD_FAILED:{type(exc).__name__}"

    @property
    def device(self) -> str:
        return self._runtime_device

    def predict(self, image: Image.Image) -> SyntheticDetectorScore:
        return self.predict_many([image])[0]

    def predict_many(self, images: list[Image.Image]) -> list[SyntheticDetectorScore]:
        if not self.available or self._model is None or self._torch is None:
            raise RuntimeError(self.unavailable_reason or "COMMUNITY_FORENSICS_UNAVAILABLE")
        if not images:
            return []
        tensor = self._torch.cat(
            [_community_forensics_tensor(image, self._torch) for image in images], dim=0
        ).to(self._runtime_device)
        with self._torch.inference_mode():
            output = self._model(tensor)
            logits = output.reshape(-1).detach().float().cpu().tolist()
        if len(logits) != len(images):
            raise RuntimeError("COMMUNITY_FORENSICS_BATCH_RESULT_COUNT_INVALID")
        return [
            SyntheticDetectorScore(
                provider=self.name,
                score=_sigmoid(float(logit)),
                calibrated=False,
                model_version="official-384-checkpoint",
                artifact_sha256=self.artifact_sha256,
                preprocessing_identity=self.preprocessing_identity,
                source_scope="THOUSANDS_OF_DIFFUSION_AND_COMMERCIAL_GENERATORS",
                evidence_family=self.evidence_family,
                score_semantics="SIGMOID_MODEL_OUTPUT_NOT_DEPLOYMENT_PROBABILITY",
                warnings=("SIGMOID_OUTPUT_NOT_DEPLOYMENT_CALIBRATED",),
            )
            for logit in logits
        ]


class TorchScriptSyntheticDetector:
    name = "operator-torchscript-synthetic-detector"
    evidence_family = "OPERATOR_TORCHSCRIPT"
    preprocessing_identity = "IMAGENET_FORCE_FIT_384_V1"

    def __init__(self, model_path: Path, requested_device: str = "auto") -> None:
        self.model_path = Path(model_path)
        self.available = False
        self.unavailable_reason: str | None = None
        self._model = None
        self._torch = None
        self._runtime_device = "unavailable"
        if not self.model_path.exists():
            self.unavailable_reason = "SYNTHETIC_TORCHSCRIPT_MODEL_NOT_FOUND"
            return
        try:
            import torch  # type: ignore

            runtime_device = _device(requested_device, torch)
            model = torch.jit.load(str(self.model_path), map_location=runtime_device)
            model.eval()
            self._model = model
            self._torch = torch
            self._runtime_device = runtime_device
            self.available = True
        except Exception as exc:
            self.unavailable_reason = f"SYNTHETIC_TORCHSCRIPT_LOAD_FAILED:{type(exc).__name__}"

    @property
    def device(self) -> str:
        return self._runtime_device

    def predict(self, image: Image.Image) -> SyntheticDetectorScore:
        if not self.available or self._model is None or self._torch is None:
            raise RuntimeError(self.unavailable_reason or "SYNTHETIC_TORCHSCRIPT_UNAVAILABLE")
        tensor = _imagenet_tensor(image, 384, self._torch).to(self._runtime_device)
        with self._torch.inference_mode():
            raw = float(self._model(tensor).reshape(-1)[0].detach().cpu())
        score = raw if 0.0 <= raw <= 1.0 else 1.0 / (1.0 + math.exp(-max(min(raw, 50), -50)))
        return SyntheticDetectorScore(
            provider=self.name,
            score=score,
            calibrated=False,
            evidence_family=self.evidence_family,
            preprocessing_identity=self.preprocessing_identity,
            score_semantics="OPERATOR_MODEL_SCORE_NOT_DEPLOYMENT_PROBABILITY",
            warnings=("OPERATOR_MODEL_SCORE_NOT_ASSUMED_CALIBRATED",),
        )


class SightengineDetector:
    """Direct adapter for Sightengine's ``genai`` image-detection model.

    Sightengine accepts an image upload plus ``api_user`` and ``api_secret``. The
    detector intentionally uploads the original accepted bytes once per scan rather
    than submitting CreatorProof's JPEG/crop stress views. This keeps a cloud
    detector's original-image verdict from being diluted by synthetic transforms,
    avoids multiplying paid API operations, and lets its own documented robustness
    handling operate on the real upload.

    The API's response exposes a global ``type.ai_generated`` confidence and may
    expose ``type.ai_generators`` category scores. Those fields are retained as
    provider-supplied review evidence only. They are not provenance and do not tell
    us which pixels caused the model's result.
    """

    name = "sightengine-genai"
    evidence_family = "SIGHTENGINE_CLOUD_GENAI"
    preprocessing_identity = "SIGHTENGINE_GENAI_ORIGINAL_MEDIA_UPLOAD_V1"
    source_scope = "SIGHTENGINE_GENAI_DECLARED_AI_GENERATED_OR_AI_EDITED_IMAGES"
    endpoint = "https://api.sightengine.com/1.0/check.json"
    model_name = "genai"
    uses_original_media_only = True

    def __init__(
        self,
        *,
        api_user: str = "",
        api_secret: str = "",
        api_key: str = "",
        timeout_seconds: float = 20.0,
        max_workers: int = 2,
    ) -> None:
        split_user, split_secret = self._split_api_key(api_key)
        self.api_user = (api_user or split_user).strip()
        # Kept private in all externally returned status/evidence objects. The public
        # ``api_secret`` property exists only for backwards-compatible construction
        # checks; neither it nor the user ID is serialised by this provider.
        self.api_secret = (api_secret or split_secret).strip()
        self.timeout_seconds = min(max(float(timeout_seconds), 1.0), 120.0)
        self.max_workers = min(max(int(max_workers), 1), 8)
        self.available = bool(self.api_user and self.api_secret)
        self.unavailable_reason = None if self.available else "SIGHTENGINE_API_CREDENTIALS_MISSING"
        self.artifact_sha256: str | None = None

    @staticmethod
    def _split_api_key(api_key: str) -> tuple[str, str]:
        value = str(api_key or "").strip()
        if not value or ":" not in value:
            return "", ""
        user, secret = value.split(":", 1)
        return user.strip(), secret.strip()

    @staticmethod
    def _score(value: Any, *, field: str) -> float:
        try:
            score = float(value)
        except (TypeError, ValueError) as exc:
            raise RuntimeError(f"SIGHTENGINE_RESPONSE_{field.upper()}_INVALID") from exc
        if not math.isfinite(score) or not 0.0 <= score <= 1.0:
            raise RuntimeError(f"SIGHTENGINE_RESPONSE_{field.upper()}_INVALID")
        return score

    @staticmethod
    def _safe_identifier(value: Any, *, maximum_length: int = 160) -> str | None:
        text = str(value or "").strip()
        if not text:
            return None
        # Request IDs are an audit reference, not a place to reproduce arbitrary
        # provider data. Keep only compact, non-control text.
        cleaned = "".join(character for character in text if character.isprintable())
        return cleaned[:maximum_length] or None

    @classmethod
    def _score_map(cls, value: Any) -> dict[str, float]:
        if not isinstance(value, dict):
            return {}
        output: dict[str, float] = {}
        for key, raw_score in value.items():
            name = str(key or "").strip().lower()
            if not name or len(name) > 80:
                continue
            try:
                output[name] = cls._score(raw_score, field="generator_score")
            except RuntimeError:
                # Optional category fields must not make a valid global model result
                # unusable. They are simply omitted and the absence is recorded.
                continue
        return dict(sorted(output.items()))

    @staticmethod
    def _media_type(raw: bytes) -> tuple[str, str]:
        try:
            with Image.open(BytesIO(raw)) as opened:
                image_format = (opened.format or "").upper()
        except (OSError, ValueError):
            return "candidate.bin", "application/octet-stream"
        by_format = {
            "JPEG": ("candidate.jpg", "image/jpeg"),
            "PNG": ("candidate.png", "image/png"),
            "WEBP": ("candidate.webp", "image/webp"),
            "GIF": ("candidate.gif", "image/gif"),
            "AVIF": ("candidate.avif", "image/avif"),
        }
        return by_format.get(image_format, ("candidate.bin", "application/octet-stream"))

    @staticmethod
    def _error_for_status(status_code: int) -> Exception:
        if status_code in {401, 403}:
            return PermissionError("SIGHTENGINE_AUTH_INVALID")
        if status_code == 429:
            return RuntimeError("SIGHTENGINE_RATE_LIMITED")
        if status_code >= 500:
            return RuntimeError("SIGHTENGINE_SERVICE_UNAVAILABLE")
        return RuntimeError("SIGHTENGINE_HTTP_REQUEST_REJECTED")

    def _request(self, raw: bytes, *, filename: str, content_type: str) -> SyntheticDetectorScore:
        if not self.available:
            raise RuntimeError(self.unavailable_reason or "SIGHTENGINE_UNAVAILABLE")
        if not raw:
            raise ValueError("SIGHTENGINE_MEDIA_EMPTY")
        try:
            with httpx.Client(
                timeout=httpx.Timeout(self.timeout_seconds),
                follow_redirects=False,
            ) as client:
                response = client.post(
                    self.endpoint,
                    data={
                        "models": self.model_name,
                        "api_user": self.api_user,
                        "api_secret": self.api_secret,
                    },
                    files={"media": (filename, raw, content_type)},
                )
        except httpx.TimeoutException as exc:
            raise TimeoutError("SIGHTENGINE_REQUEST_TIMEOUT") from exc
        except httpx.RequestError as exc:
            raise RuntimeError("SIGHTENGINE_NETWORK_ERROR") from exc

        if int(response.status_code) != 200:
            raise self._error_for_status(int(response.status_code))
        try:
            payload = response.json()
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise RuntimeError("SIGHTENGINE_RESPONSE_INVALID_JSON") from exc
        if not isinstance(payload, dict) or payload.get("status") != "success":
            # Do not include the upstream message: it can be verbose, untrusted, or
            # inadvertently disclose sensitive request configuration in a future API.
            raise RuntimeError("SIGHTENGINE_API_FAILURE")
        type_payload = payload.get("type")
        if not isinstance(type_payload, dict):
            raise RuntimeError("SIGHTENGINE_RESPONSE_TYPE_MISSING")
        if "ai_generated" not in type_payload:
            raise RuntimeError("SIGHTENGINE_RESPONSE_AI_GENERATED_MISSING")
        score = self._score(type_payload["ai_generated"], field="ai_generated")

        # ``ai_generators`` is the documented name. ``details`` is accepted as a
        # narrow compatibility input for older mocked responses, never advertised as
        # a guaranteed Sightengine contract.
        generator_scores = self._score_map(
            type_payload.get("ai_generators")
            if isinstance(type_payload.get("ai_generators"), dict)
            else type_payload.get("details")
        )
        secondary_scores = self._score_map(
            {
                key: value
                for key, value in type_payload.items()
                if key not in {"ai_generated", "ai_generators", "details"}
            }
        )
        request_payload = payload.get("request") if isinstance(payload.get("request"), dict) else {}
        request_id = self._safe_identifier(request_payload.get("id"))
        operations = request_payload.get("operations")
        if not isinstance(operations, int) or operations < 0:
            operations = None
        warnings = [
            "SIGHTENGINE_VENDOR_SCORE_NOT_LOCALLY_CALIBRATED",
            "SIGHTENGINE_REMOTE_MODEL_VERSION_NOT_PINNED",
            "SIGHTENGINE_GENERATOR_CATEGORIES_ARE_NOT_PROVENANCE",
        ]
        if not generator_scores:
            warnings.append("SIGHTENGINE_GENERATOR_BREAKDOWN_NOT_RETURNED")
        details: dict[str, Any] = {
            "model": self.model_name,
            "request_id": request_id,
            "operations": operations,
            "global_ai_generated_score": round(score, 6),
            "generator_scores": generator_scores,
            # Retained as a compatibility alias for existing API consumers. New
            # callers should use ``generator_scores``.
            "generator_details": generator_scores,
            "secondary_scores": secondary_scores,
            "input_mode": "ORIGINAL_MEDIA_UPLOAD",
            "explanation_scope": (
                "SIGHTENGINE_RETURNS_GLOBAL_AND_OPTIONAL_GENERATOR_CATEGORY_SCORES; "
                "IT_DOES_NOT_RETURN_A_PIXEL_LEVEL_EXPLANATION"
            ),
        }
        # A compact compatibility surface for provider-returned numeric fields such
        # as ``photorealistic``. It is descriptive only and not treated as an AI cue.
        details.update(secondary_scores)
        return SyntheticDetectorScore(
            provider=self.name,
            score=score,
            calibrated=False,
            model_version="sightengine-genai-api-unversioned",
            source_scope=self.source_scope,
            evidence_family=self.evidence_family,
            artifact_sha256=None,
            preprocessing_identity=self.preprocessing_identity,
            score_semantics=(
                "SIGHTENGINE_GENAI_VENDOR_MODEL_CONFIDENCE_NOT_CREATORPROOF_CALIBRATED_PROBABILITY"
            ),
            warnings=tuple(warnings),
            details=details,
        )

    def predict_media(self, raw: bytes, *, filename: str | None = None) -> SyntheticDetectorScore:
        # Do not send the user's local filename to a third party. The bytes determine
        # a generic extension, which is all the multipart API needs.
        del filename
        inferred_filename, content_type = self._media_type(raw)
        return self._request(
            raw,
            filename=inferred_filename,
            content_type=content_type,
        )

    def predict(self, image: Image.Image) -> SyntheticDetectorScore:
        """Compatibility path for diagnostics; production scans use ``predict_media``."""

        buffer = BytesIO()
        image.convert("RGB").save(buffer, format="PNG")
        return self._request(
            buffer.getvalue(),
            filename="creatorproof-rendered.png",
            content_type="image/png",
        )

    def predict_many(self, images: list[Image.Image]) -> list[SyntheticDetectorScore | Exception]:
        """Compatibility helper; scan routing deliberately does not call this method.

        It keeps diagnostics/test callers safe from one failure aborting all images,
        but each image consumes an independent external request.
        """

        if not images:
            return []
        with ThreadPoolExecutor(max_workers=min(self.max_workers, len(images))) as executor:
            futures = [executor.submit(self.predict, image) for image in images]
            results: list[SyntheticDetectorScore | Exception] = []
            for future in futures:
                try:
                    results.append(future.result())
                except Exception as exc:
                    results.append(exc)
            return results

    def status(self) -> dict:
        return {
            "provider": self.name,
            "available": self.available,
            "reason": self.unavailable_reason,
            "model": self.model_name,
            "input_mode": "ORIGINAL_MEDIA_UPLOAD",
            "credentials_configured": self.available,
            "credential_values_exposed": False,
        }


class ExternalJsonSyntheticDetector:
    """Shell-free adapter with a batched manifest path and legacy compatibility.

    A command containing ``{manifest}`` is invoked once for all scan views and must
    emit ``{"results": [{"id": "0", "score": 0..1}, ...]}``. Older ``{image}``
    commands still work, but all of their invocations share one detector-level
    deadline instead of receiving a fresh timeout for every transformed view.
    """

    def __init__(self, spec: dict, *, maximum_timeout_seconds: int = 120) -> None:
        self.name = str(spec.get("name") or "external-synthetic-detector")
        self.command = shlex.split(str(spec.get("command") or ""))
        requested_timeout = int(spec.get("timeout_seconds") or maximum_timeout_seconds)
        self.timeout = min(max(1, requested_timeout), maximum_timeout_seconds)
        self.evidence_family = str(spec.get("evidence_family") or "EXTERNAL_UNSPECIFIED").upper()
        self.source_scope = str(spec.get("source_scope") or "UNKNOWN_GENERATORS")
        self.declared_calibration_ignored = bool(spec.get("allow_declared_calibration", False))
        self.batch_available = any("{manifest}" in part for part in self.command)
        self.single_image_available = any("{image}" in part for part in self.command)
        spec_valid = bool(self.command and (self.batch_available or self.single_image_available))
        executable = self.command[0] if self.command else ""
        self.executable_path = (
            shutil.which(executable)
            if executable and not Path(executable).is_absolute()
            else executable
            if executable and Path(executable).is_file()
            else None
        )
        self.available = bool(spec_valid and self.executable_path)
        self.unavailable_reason = (
            None
            if self.available
            else "INVALID_EXTERNAL_DETECTOR_SPEC"
            if not spec_valid
            else f"EXTERNAL_DETECTOR_EXECUTABLE_NOT_FOUND:{executable}"
        )

    def _parse_score(self, payload: dict) -> SyntheticDetectorScore:
        score = float(payload["score"])
        if not 0.0 <= score <= 1.0:
            raise ValueError("External detector score must be within [0, 1]")
        warnings = [str(item) for item in payload.get("warnings") or []]
        if payload.get("calibrated") or self.declared_calibration_ignored:
            warnings.append("EXTERNAL_PROVIDER_CALIBRATION_DECLARATION_IGNORED")
        return SyntheticDetectorScore(
            provider=str(payload.get("provider") or self.name),
            score=score,
            calibrated=False,
            model_version=str(payload.get("version")) if payload.get("version") else None,
            source_scope=str(payload.get("source_scope") or self.source_scope),
            evidence_family=self.evidence_family,
            artifact_sha256=(
                str(payload.get("artifact_sha256")) if payload.get("artifact_sha256") else None
            ),
            preprocessing_identity=(
                str(payload.get("preprocessing_identity"))
                if payload.get("preprocessing_identity")
                else None
            ),
            score_semantics=str(
                payload.get("score_semantics") or "EXTERNAL_RAW_SCORE_NOT_PROBABILITY"
            ),
            warnings=tuple(warnings),
        )

    def _run(self, command: list[str], *, timeout: float) -> dict:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=max(0.1, timeout),
        )
        if completed.returncode != 0:
            raise RuntimeError(f"EXTERNAL_DETECTOR_NONZERO_EXIT: {completed.stderr}")
        payload = json.loads(completed.stdout)
        if not isinstance(payload, dict):
            raise TypeError("EXTERNAL_DETECTOR_JSON_MUST_BE_OBJECT")
        return payload

    @staticmethod
    def _save_views(images: list[Image.Image], root: Path) -> list[Path]:
        paths = []
        for index, image in enumerate(images):
            path = root / f"view-{index:03d}.png"
            image.convert("RGB").save(path, format="PNG")
            paths.append(path)
        return paths

    def predict_many(self, images: list[Image.Image]) -> list[SyntheticDetectorScore | Exception]:
        if not self.available:
            raise RuntimeError(self.unavailable_reason or "EXTERNAL_DETECTOR_UNAVAILABLE")
        if not images:
            return []
        deadline = time.monotonic() + self.timeout
        with tempfile.TemporaryDirectory(prefix="creatorproof-synthetic-batch-") as temp_dir:
            root = Path(temp_dir)
            paths = self._save_views(images, root)
            if self.batch_available:
                manifest_path = root / "manifest.json"
                manifest_path.write_text(
                    json.dumps(
                        {
                            "schema": "creatorproof.synthetic_batch.v1",
                            "items": [
                                {"id": str(index), "path": str(path)}
                                for index, path in enumerate(paths)
                            ],
                        }
                    ),
                    encoding="utf-8",
                )
                command = [part.replace("{manifest}", str(manifest_path)) for part in self.command]
                payload = self._run(command, timeout=deadline - time.monotonic())
                raw_results = payload.get("results")
                if not isinstance(raw_results, list):
                    raise TypeError("EXTERNAL_BATCH_RESULTS_MUST_BE_LIST")
                if len(raw_results) != len(paths):
                    raise RuntimeError("EXTERNAL_BATCH_RESULT_COUNT_INVALID")
                by_id = {
                    str(item.get("id")): item
                    for item in raw_results
                    if isinstance(item, dict) and item.get("id") is not None
                }
                if set(by_id) != {str(index) for index in range(len(paths))}:
                    raise RuntimeError("EXTERNAL_BATCH_RESULT_IDS_INVALID")
                return [self._parse_score(by_id[str(index)]) for index in range(len(paths))]

            results: list[SyntheticDetectorScore | Exception] = []
            for path in paths:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    results.append(TimeoutError("EXTERNAL_DETECTOR_SCAN_BUDGET_EXHAUSTED"))
                    continue
                command = [part.replace("{image}", str(path)) for part in self.command]
                try:
                    results.append(self._parse_score(self._run(command, timeout=remaining)))
                except Exception as exc:
                    results.append(exc)
            return results

    def predict(self, image: Image.Image) -> SyntheticDetectorScore:
        result = self.predict_many([image])[0]
        if isinstance(result, Exception):
            raise result
        return result


class SyntheticDetectorRouter:
    def __init__(
        self,
        *,
        mode: str,
        community_model_path: Path,
        community_expected_sha256: str = "",
        torchscript_model_path: Path,
        device: str,
        external_detectors_json: str,
        evidence_family_registry_path: Path,
        calibration_path: Path,
        min_calibration_samples: int,
        min_calibration_class_samples: int,
        external_timeout_seconds: int = 120,
        calibration_domain_id: str = "",
        crop_policy_id: str = "",
        model_bundle_manifest_digest: str = "",
        sightengine_api_user: str = "",
        sightengine_api_secret: str = "",
        sightengine_timeout_seconds: float = 20.0,
    ) -> None:
        requested_mode = str(mode).strip().lower()
        self.mode = requested_mode
        self.configuration_warning: str | None = None
        local_candidates = []
        if requested_mode in {"auto", "sightengine", "community"}:
            local_candidates.append(
                CommunityForensicsDetector(
                    community_model_path,
                    device,
                    expected_sha256=community_expected_sha256,
                )
            )
        if requested_mode in {"auto", "sightengine", "torchscript"}:
            local_candidates.append(TorchScriptSyntheticDetector(torchscript_model_path, device))
        try:
            external_specs = json.loads(external_detectors_json)
            if not isinstance(external_specs, list):
                raise TypeError
        except (json.JSONDecodeError, TypeError):
            external_specs = []
            self.configuration_warning = "INVALID_SYNTHETIC_EXTERNAL_DETECTORS_JSON"
        local_candidates.extend(
            ExternalJsonSyntheticDetector(
                spec,
                maximum_timeout_seconds=external_timeout_seconds,
            )
            for spec in external_specs
        )

        self.sightengine = (
            SightengineDetector(
                api_user=sightengine_api_user,
                api_secret=sightengine_api_secret,
                timeout_seconds=sightengine_timeout_seconds,
            )
            if requested_mode in {"auto", "sightengine"}
            else None
        )
        primary_candidates = [self.sightengine] if self.sightengine is not None else []
        self.primary_detector = (
            self.sightengine
            if (
                requested_mode != "off"
                and self.sightengine is not None
                and self.sightengine.available
            )
            else None
        )
        self.fallback_detectors = (
            [item for item in local_candidates if item.available] if requested_mode != "off" else []
        )
        # Existing callers use ``detectors`` for a complete status list. Runtime
        # analysis uses primary_detector/fallback_detectors so a healthy Sightengine
        # response does not also run local models or consume extra resources.
        self.detectors = (
            [self.primary_detector] if self.primary_detector is not None else []
        ) + self.fallback_detectors
        unavailable_candidates = [*primary_candidates, *local_candidates]
        self.unavailable = [
            {"provider": item.name, "reason": item.unavailable_reason}
            for item in unavailable_candidates
            if not item.available
        ]
        self.name = (
            "sightengine-primary-local-fallback-synthetic-router-v1"
            if requested_mode in {"auto", "sightengine"}
            else "evidence-family-synthetic-ensemble-v3"
        )
        self.family_registry = SyntheticEvidenceFamilyRegistry(evidence_family_registry_path)
        self.calibration = SyntheticCalibrationRegistry(
            calibration_path,
            min_samples=min_calibration_samples,
            min_class_samples=min_calibration_class_samples,
            expected_domain_id=calibration_domain_id,
            expected_crop_policy_id=crop_policy_id,
            expected_model_bundle_manifest_digest=model_bundle_manifest_digest,
        )

    @property
    def available(self) -> bool:
        return bool(self.detectors)

    def status(self) -> dict:
        primary_status = self.sightengine.status() if self.sightengine is not None else None
        if self.mode == "off":
            primary_state = "DISABLED"
        elif self.primary_detector is not None:
            primary_state = "ACTIVE"
        elif self.sightengine is not None:
            primary_state = "UNAVAILABLE"
        else:
            primary_state = "NOT_SELECTED"
        return {
            "provider": self.name,
            "available": self.available,
            "active_detectors": [item.name for item in self.detectors],
            "declared_evidence_families": sorted(
                {getattr(item, "evidence_family", "UNSPECIFIED") for item in self.detectors}
            ),
            "active_evidence_families": sorted(
                {
                    str(self.family_registry.entries[item.name]["evidence_family"])
                    for item in self.detectors
                    if item.name in self.family_registry.entries
                }
            ),
            "evidence_family_registry": self.family_registry.status(),
            "batched_detectors": [
                item.name
                for item in self.detectors
                if callable(getattr(item, "predict_many", None))
            ],
            "unavailable_detectors": self.unavailable,
            "configuration_warning": self.configuration_warning,
            "routing": {
                "mode": self.mode,
                "primary_provider": (
                    self.sightengine.name if self.sightengine is not None else None
                ),
                "primary_state": primary_state,
                "primary": primary_status,
                "fallback_policy": "LOCAL_FALLBACK_ON_PRIMARY_OPERATIONAL_FAILURE",
                "fallback_detectors": [item.name for item in self.fallback_detectors],
                "local_fallback_available": bool(self.fallback_detectors),
            },
            "devices": sorted({getattr(item, "device", "external") for item in self.detectors}),
            "component_artifacts": [
                {
                    "provider": item.name,
                    "artifact_sha256": getattr(item, "artifact_sha256", None),
                    "preprocessing_identity": getattr(item, "preprocessing_identity", None),
                }
                for item in self.detectors
            ],
            "calibration": self.calibration.status(),
        }

    def govern_score(self, score: SyntheticDetectorScore, detector) -> SyntheticDetectorScore:
        return self.family_registry.govern(score, detector)

    def calibrate(
        self,
        provider: str,
        model_version: str | None,
        score: float,
        artifact_sha256: str | None = None,
        preprocessing_identity: str | None = None,
    ) -> tuple[float, dict]:
        return self.calibration.apply(
            provider,
            model_version,
            score,
            artifact_sha256,
            preprocessing_identity,
        )
