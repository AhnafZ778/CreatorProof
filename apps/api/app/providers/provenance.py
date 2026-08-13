import json
import shutil
import subprocess
from pathlib import Path

from app.domain.enums import ProvenanceStatus
from app.providers.contracts import ProvenanceEvidence


class NotConfiguredProvenanceProvider:
    """Explicit capability state until the official C2PA SDK is integrated and tested."""

    name = "not-configured"

    def inspect(self, source_path: Path) -> ProvenanceEvidence:
        del source_path
        return ProvenanceEvidence(
            status=ProvenanceStatus.NOT_CHECKED,
            provider=self.name,
            reason_codes=["C2PA_PROVIDER_NOT_CONFIGURED"],
        )


_AI_SOURCE_MARKERS = (
    "trainedalgorithmicmedia",
    "compositewithtrainedalgorithmicmedia",
    "algorithmicmedia",
    "compositesynthetic",
)


def _walk(value):
    if isinstance(value, dict):
        for key, item in value.items():
            yield str(key), item
            yield from _walk(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk(item)


def _strings(value) -> list[str]:
    found: list[str] = []
    if isinstance(value, str):
        found.append(value)
    for _, item in _walk(value):
        if isinstance(item, str):
            found.append(item)
    return found


class C2PAToolProvenanceProvider:
    """Read and validate C2PA manifests using the official c2patool binary.

    The adapter intentionally reports trust separately from manifest validity. It
    never treats missing Content Credentials as proof that media is camera-made.
    """

    name = "c2patool-official"

    def __init__(self, binary: str = "c2patool", timeout_seconds: int = 20) -> None:
        self.binary = binary
        self.timeout_seconds = timeout_seconds
        self.available = shutil.which(binary) is not None
        self.unavailable_reason = None if self.available else "C2PATOOL_BINARY_NOT_FOUND"

    @staticmethod
    def _summary(payload: dict) -> dict:
        strings = _strings(payload)
        ai_markers = sorted(
            {
                marker
                for text in strings
                for marker in _AI_SOURCE_MARKERS
                if marker in text.casefold().replace("-", "").replace("_", "")
            }
        )
        statuses = [
            text
            for text in strings
            if any(token in text.casefold() for token in ("trusted", "invalid", "error"))
        ][:20]
        active = payload.get("active_manifest") or payload.get("activeManifest")
        manifests = payload.get("manifests") or {}
        active_manifest = manifests.get(active, {}) if isinstance(manifests, dict) else {}
        claim_generator = None
        if isinstance(active_manifest, dict):
            claim_generator = active_manifest.get("claim_generator") or active_manifest.get(
                "claimGenerator"
            )
        return {
            "active_manifest": active,
            "claim_generator": claim_generator,
            "ai_source_markers": ai_markers,
            "ai_assertion_present": bool(ai_markers),
            "validation_signals": statuses,
            "raw_manifest_included": False,
        }

    def inspect(self, source_path: Path) -> ProvenanceEvidence:
        if not self.available:
            return ProvenanceEvidence(
                status=ProvenanceStatus.NOT_CHECKED,
                provider=self.name,
                reason_codes=[self.unavailable_reason or "C2PA_PROVIDER_UNAVAILABLE"],
            )
        try:
            completed = subprocess.run(
                [self.binary, str(source_path)],
                check=False,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            return ProvenanceEvidence(
                status=ProvenanceStatus.ERROR,
                provider=self.name,
                reason_codes=["C2PA_INSPECTION_TIMEOUT"],
            )
        except OSError:
            return ProvenanceEvidence(
                status=ProvenanceStatus.ERROR,
                provider=self.name,
                reason_codes=["C2PA_INSPECTION_EXECUTION_FAILED"],
            )

        combined = f"{completed.stdout}\n{completed.stderr}".casefold()
        if completed.returncode != 0 and any(
            marker in combined for marker in ("no claim", "no manifest", "manifest not found")
        ):
            return ProvenanceEvidence(
                status=ProvenanceStatus.NOT_PRESENT,
                provider=self.name,
                reason_codes=[
                    "C2PA_MANIFEST_NOT_PRESENT",
                    "ABSENCE_DOES_NOT_ESTABLISH_HUMAN_ORIGIN",
                ],
            )
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError:
            if completed.returncode != 0:
                return ProvenanceEvidence(
                    status=ProvenanceStatus.ERROR,
                    provider=self.name,
                    reason_codes=["C2PA_OUTPUT_NOT_JSON", "C2PA_INSPECTION_FAILED"],
                )
            return ProvenanceEvidence(
                status=ProvenanceStatus.ERROR,
                provider=self.name,
                reason_codes=["C2PA_OUTPUT_NOT_JSON"],
            )

        if not isinstance(payload, dict) or not (
            payload.get("active_manifest")
            or payload.get("activeManifest")
            or payload.get("manifests")
        ):
            return ProvenanceEvidence(
                status=ProvenanceStatus.NOT_PRESENT,
                provider=self.name,
                reason_codes=[
                    "C2PA_MANIFEST_NOT_PRESENT",
                    "ABSENCE_DOES_NOT_ESTABLISH_HUMAN_ORIGIN",
                ],
            )

        summary = self._summary(payload)
        text_signals = " ".join(_strings(payload)).casefold()
        invalid = completed.returncode != 0 or any(
            marker in text_signals
            for marker in ("validation error", "invalid claim", "invalid signature", "tampered")
        )
        explicitly_trusted = any(
            marker in text_signals for marker in ("valid_trusted", "signing credential trusted")
        )
        if invalid:
            state = ProvenanceStatus.INVALID
            reasons = ["C2PA_MANIFEST_INVALID_OR_TAMPERED"]
        elif explicitly_trusted:
            state = ProvenanceStatus.VALID_TRUSTED
            reasons = ["C2PA_MANIFEST_VALID", "C2PA_SIGNER_TRUST_CONFIRMED"]
        else:
            state = ProvenanceStatus.VALID_UNTRUSTED
            reasons = ["C2PA_MANIFEST_VALID", "C2PA_SIGNER_TRUST_NOT_CONFIRMED"]
        if summary["ai_assertion_present"]:
            reasons.append("C2PA_GENERATIVE_AI_ACTION_ASSERTED")
        return ProvenanceEvidence(
            status=state,
            provider=self.name,
            reason_codes=reasons,
            manifest_summary=summary,
        )


class ProvenanceRouter:
    def __init__(self, *, mode: str, binary: str, timeout_seconds: int) -> None:
        official = C2PAToolProvenanceProvider(binary, timeout_seconds)
        if mode == "off":
            self.active = NotConfiguredProvenanceProvider()
        elif official.available:
            self.active = official
        else:
            self.active = official
        self.name = self.active.name

    def inspect(self, source_path: Path) -> ProvenanceEvidence:
        return self.active.inspect(source_path)

    def status(self) -> dict:
        return {
            "provider": self.name,
            "available": bool(getattr(self.active, "available", False)),
            "reason": getattr(self.active, "unavailable_reason", None),
        }
