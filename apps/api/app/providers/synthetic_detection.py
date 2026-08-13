from __future__ import annotations

import json
import math
import shlex
import subprocess
import tempfile
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

from app.providers.contracts import SyntheticDetectorScore


def _sigmoid(value: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(min(float(value), 50.0), -50.0)))


def _logit(value: float) -> float:
    clipped = min(max(float(value), 1e-6), 1.0 - 1e-6)
    return math.log(clipped / (1.0 - clipped))


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
    ) -> None:
        self.path = Path(path)
        self.entries: dict[str, dict] = {}
        self.state = "NOT_CONFIGURED"
        self.reason: str | None = None
        if not self.path.exists():
            self.reason = "SYNTHETIC_CALIBRATION_FILE_NOT_FOUND"
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if payload.get("schema") != "creatorproof.synthetic_calibration.v1":
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
                adequate = (
                    sample_count >= min_samples
                    and positive_count >= min_class_samples
                    and negative_count >= min_class_samples
                    and slope > 0.0
                    and math.isfinite(slope)
                    and math.isfinite(intercept)
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
        calibrated = _sigmoid(float(entry["slope"]) * _logit(raw_score) + float(entry["intercept"]))
        return calibrated, {
            "applied": True,
            "state": "HELD_OUT_PLATT_CALIBRATION",
            "dataset_id": entry.get("dataset_id"),
            "sample_count": entry.get("sample_count"),
            "brier_score": entry.get("brier_score"),
            "expected_calibration_error": entry.get("expected_calibration_error"),
            "semantics": "CALIBRATED_ON_RECORDED_DOMAIN_NOT_UNIVERSAL_PROBABILITY",
        }

    def status(self) -> dict:
        return {
            "state": self.state,
            "providers": sorted(self.entries),
            "reason": self.reason,
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

    def __init__(self, model_path: Path, requested_device: str = "auto") -> None:
        self.model_path = Path(model_path)
        self.requested_device = requested_device
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

            weights = next(iter(sorted(self.model_path.glob("*.safetensors"))), None)
            if weights is None:
                self.unavailable_reason = "COMMUNITY_FORENSICS_SAFETENSORS_NOT_FOUND"
                return
            runtime_device = _device(requested_device, torch)
            model = timm.create_model(
                "vit_small_patch16_384.augreg_in21k_ft_in1k",
                pretrained=False,
                num_classes=1,
            )
            state = load_file(str(weights), device="cpu")
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
        if not self.available or self._model is None or self._torch is None:
            raise RuntimeError(self.unavailable_reason or "COMMUNITY_FORENSICS_UNAVAILABLE")
        tensor = _community_forensics_tensor(image, self._torch).to(self._runtime_device)
        with self._torch.inference_mode():
            output = self._model(tensor)
            logit = float(output.reshape(-1)[0].detach().cpu())
        score = 1.0 / (1.0 + math.exp(-max(min(logit, 50.0), -50.0)))
        return SyntheticDetectorScore(
            provider=self.name,
            score=score,
            calibrated=False,
            model_version="official-384-checkpoint",
            source_scope="THOUSANDS_OF_DIFFUSION_AND_COMMERCIAL_GENERATORS",
            evidence_family=self.evidence_family,
            score_semantics="SIGMOID_MODEL_OUTPUT_NOT_DEPLOYMENT_PROBABILITY",
            warnings=("SIGMOID_OUTPUT_NOT_DEPLOYMENT_CALIBRATED",),
        )


class TorchScriptSyntheticDetector:
    name = "operator-torchscript-synthetic-detector"
    evidence_family = "OPERATOR_TORCHSCRIPT"

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
            score_semantics="OPERATOR_MODEL_SCORE_NOT_DEPLOYMENT_PROBABILITY",
            warnings=("OPERATOR_MODEL_SCORE_NOT_ASSUMED_CALIBRATED",),
        )


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
        self.allow_declared_calibration = bool(spec.get("allow_declared_calibration", False))
        self.batch_available = any("{manifest}" in part for part in self.command)
        self.single_image_available = any("{image}" in part for part in self.command)
        self.available = bool(
            self.command and (self.batch_available or self.single_image_available)
        )
        self.unavailable_reason = None if self.available else "INVALID_EXTERNAL_DETECTOR_SPEC"

    def _parse_score(self, payload: dict) -> SyntheticDetectorScore:
        score = float(payload["score"])
        if not 0.0 <= score <= 1.0:
            raise ValueError("External detector score must be within [0, 1]")
        return SyntheticDetectorScore(
            provider=str(payload.get("provider") or self.name),
            score=score,
            calibrated=(self.allow_declared_calibration and bool(payload.get("calibrated", False))),
            model_version=str(payload.get("version")) if payload.get("version") else None,
            source_scope=str(payload.get("source_scope") or self.source_scope),
            evidence_family=self.evidence_family,
            score_semantics=str(
                payload.get("score_semantics") or "EXTERNAL_RAW_SCORE_NOT_PROBABILITY"
            ),
            warnings=tuple(str(item) for item in payload.get("warnings") or []),
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
        torchscript_model_path: Path,
        device: str,
        external_detectors_json: str,
        calibration_path: Path,
        min_calibration_samples: int,
        min_calibration_class_samples: int,
        external_timeout_seconds: int = 120,
    ) -> None:
        candidates = []
        if mode in {"auto", "community"}:
            candidates.append(CommunityForensicsDetector(community_model_path, device))
        if mode in {"auto", "torchscript"}:
            candidates.append(TorchScriptSyntheticDetector(torchscript_model_path, device))
        try:
            external_specs = json.loads(external_detectors_json)
            if not isinstance(external_specs, list):
                raise TypeError
        except (json.JSONDecodeError, TypeError):
            external_specs = []
            self.configuration_warning = "INVALID_SYNTHETIC_EXTERNAL_DETECTORS_JSON"
        else:
            self.configuration_warning = None
        candidates.extend(
            ExternalJsonSyntheticDetector(
                spec,
                maximum_timeout_seconds=external_timeout_seconds,
            )
            for spec in external_specs
        )
        self.detectors = [item for item in candidates if item.available] if mode != "off" else []
        self.unavailable = [
            {"provider": item.name, "reason": item.unavailable_reason}
            for item in candidates
            if not item.available
        ]
        self.name = "evidence-family-synthetic-ensemble-v3"
        self.calibration = SyntheticCalibrationRegistry(
            calibration_path,
            min_samples=min_calibration_samples,
            min_class_samples=min_calibration_class_samples,
        )

    @property
    def available(self) -> bool:
        return bool(self.detectors)

    def status(self) -> dict:
        return {
            "provider": self.name,
            "available": self.available,
            "active_detectors": [item.name for item in self.detectors],
            "active_evidence_families": sorted(
                {getattr(item, "evidence_family", "UNSPECIFIED") for item in self.detectors}
            ),
            "batched_detectors": [
                item.name for item in self.detectors if getattr(item, "batch_available", False)
            ],
            "unavailable_detectors": self.unavailable,
            "configuration_warning": self.configuration_warning,
            "devices": sorted({getattr(item, "device", "external") for item in self.detectors}),
            "calibration": self.calibration.status(),
        }

    def calibrate(
        self,
        provider: str,
        model_version: str | None,
        score: float,
    ) -> tuple[float, dict]:
        return self.calibration.apply(provider, model_version, score)
