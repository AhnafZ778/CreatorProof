import hashlib
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
            trust_details={
                "manifest_present": None,
                "manifest_valid": None,
                "signature_valid": None,
                "signer_trusted": None,
                "signer_trust_state": "NOT_EVALUATED",
                "relevant_ai_assertion_present": None,
                "ingredient_chain_state": "NOT_EVALUATED",
                "trust_policy_id": None,
            },
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


def _active_manifest(payload: dict) -> tuple[str | None, dict | None]:
    active = payload.get("active_manifest") or payload.get("activeManifest")
    manifests = payload.get("manifests")
    if not isinstance(active, str) or not isinstance(manifests, dict):
        return None, None
    manifest = manifests.get(active)
    return active, manifest if isinstance(manifest, dict) else None


def _validation_entries(payload: dict) -> list[tuple[str, str]]:
    entries: list[tuple[str, str]] = []

    def visit(value, bucket: str) -> None:
        if isinstance(value, dict):
            code = value.get("code")
            if isinstance(code, str) and code.strip():
                entries.append((code.strip(), bucket))
            for key, item in value.items():
                normalized_key = str(key).casefold()
                next_bucket = (
                    "failure"
                    if normalized_key in {"failure", "failures", "error", "errors"}
                    else "success"
                    if normalized_key in {"success", "successes"}
                    else "informational"
                    if normalized_key in {"informational", "info"}
                    else bucket
                )
                visit(item, next_bucket)
        elif isinstance(value, list):
            for item in value:
                visit(item, bucket)

    for key in (
        "validation_status",
        "validationStatus",
        "validation_results",
        "validationResults",
    ):
        if key in payload:
            visit(payload[key], "status")
    return entries


def _normalized_source_type(value: str) -> str:
    token = value.rsplit("/", 1)[-1].rsplit("#", 1)[-1]
    return "".join(character for character in token.casefold() if character.isalnum())


def _ai_source_markers(active_manifest: dict) -> list[str]:
    assertions = active_manifest.get("assertions")
    if not isinstance(assertions, (list, dict)):
        return []
    found: set[str] = set()
    for key, value in _walk(assertions):
        normalized_key = "".join(character for character in key.casefold() if character.isalnum())
        if normalized_key not in {"digitalsourcetype", "sourcetype"}:
            continue
        values = value if isinstance(value, list) else [value]
        for item in values:
            if not isinstance(item, str):
                continue
            normalized = _normalized_source_type(item)
            if normalized in _AI_SOURCE_MARKERS:
                found.add(normalized)
    return sorted(found)


class C2PAToolProvenanceProvider:
    """Read and validate C2PA manifests using the official c2patool binary.

    The adapter intentionally reports trust separately from manifest validity. It
    never treats missing Content Credentials as proof that media is camera-made.
    """

    name = "c2patool-official"

    def __init__(
        self,
        binary: str = "c2patool",
        timeout_seconds: int = 20,
        trust_policy_id: str = "creatorproof-c2patool-default-trust-evaluation-v1",
        expected_version: str = "",
        expected_binary_sha256: str = "",
    ) -> None:
        self.binary = binary
        self.timeout_seconds = timeout_seconds
        self.trust_policy_id = trust_policy_id
        self.expected_version = expected_version.strip()
        self.expected_binary_sha256 = expected_binary_sha256.strip().lower()
        self.binary_path = shutil.which(binary)
        self.actual_version: str | None = None
        self.actual_binary_sha256: str | None = None
        self.unavailable_reason = self._runtime_integrity_reason()
        self.available = self.unavailable_reason is None

    def _runtime_integrity_reason(self) -> str | None:
        if self.binary_path is None:
            return "C2PATOOL_BINARY_NOT_FOUND"
        binary_path = Path(self.binary_path)
        try:
            digest = hashlib.sha256()
            with binary_path.open("rb") as source:
                for block in iter(lambda: source.read(1024 * 1024), b""):
                    digest.update(block)
            self.actual_binary_sha256 = digest.hexdigest()
            completed = subprocess.run(
                [self.binary_path, "--version"],
                check=False,
                capture_output=True,
                text=True,
                timeout=min(self.timeout_seconds, 10),
            )
        except (OSError, subprocess.TimeoutExpired):
            return "C2PATOOL_IDENTITY_CHECK_FAILED"
        if completed.returncode != 0:
            return "C2PATOOL_VERSION_CHECK_FAILED"
        version_text = completed.stdout.strip()
        self.actual_version = (
            version_text.removeprefix("c2patool ").strip() if version_text else None
        )
        if self.expected_version and self.actual_version != self.expected_version:
            return "C2PATOOL_VERSION_MISMATCH"
        if self.expected_binary_sha256:
            if len(self.expected_binary_sha256) != 64 or any(
                character not in "0123456789abcdef" for character in self.expected_binary_sha256
            ):
                return "C2PATOOL_EXPECTED_SHA256_INVALID"
            if self.actual_binary_sha256 != self.expected_binary_sha256:
                return "C2PATOOL_BINARY_SHA256_MISMATCH"
        return None

    @staticmethod
    def _summary(payload: dict) -> dict:
        active, active_manifest = _active_manifest(payload)
        active_manifest = active_manifest or {}
        ai_markers = _ai_source_markers(active_manifest)
        validation_entries = _validation_entries(payload)
        return {
            "active_manifest": active,
            "claim_generator": active_manifest.get("claim_generator")
            or active_manifest.get("claimGenerator"),
            "ai_source_markers": ai_markers,
            "ai_assertion_present": bool(ai_markers),
            "validation_codes": sorted({code for code, _bucket in validation_entries}),
            "validation_schema": (
                "STRUCTURED_VALIDATION_RESULTS"
                if payload.get("validation_results") is not None
                or payload.get("validationResults") is not None
                else "STRUCTURED_VALIDATION_STATUS"
                if payload.get("validation_status") is not None
                or payload.get("validationStatus") is not None
                else "PROCESS_EXIT_STATUS_ONLY"
            ),
            "raw_manifest_included": False,
        }

    def _trust_details(
        self,
        *,
        manifest_present: bool | None,
        manifest_valid: bool | None,
        signature_valid: bool | None,
        signer_trusted: bool | None,
        ai_assertion_present: bool | None,
        ingredient_chain_state: str,
    ) -> dict:
        signer_trust_state = (
            "TRUSTED"
            if signer_trusted is True
            else "NOT_CONFIRMED"
            if signer_trusted is False
            else "NOT_EVALUATED"
        )
        return {
            "manifest_present": manifest_present,
            "manifest_valid": manifest_valid,
            "signature_valid": signature_valid,
            "signer_trusted": signer_trusted,
            "signer_trust_state": signer_trust_state,
            "relevant_ai_assertion_present": ai_assertion_present,
            "ingredient_chain_state": ingredient_chain_state,
            "trust_policy_id": self.trust_policy_id,
            "validation_tool": self.name,
        }

    def inspect(self, source_path: Path) -> ProvenanceEvidence:
        if not self.available:
            return ProvenanceEvidence(
                status=ProvenanceStatus.NOT_CHECKED,
                provider=self.name,
                reason_codes=[self.unavailable_reason or "C2PA_PROVIDER_UNAVAILABLE"],
                trust_details=self._trust_details(
                    manifest_present=None,
                    manifest_valid=None,
                    signature_valid=None,
                    signer_trusted=None,
                    ai_assertion_present=None,
                    ingredient_chain_state="NOT_EVALUATED",
                ),
            )
        try:
            completed = subprocess.run(
                [str(self.binary_path), "--detailed", str(source_path)],
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
                trust_details=self._trust_details(
                    manifest_present=None,
                    manifest_valid=None,
                    signature_valid=None,
                    signer_trusted=None,
                    ai_assertion_present=None,
                    ingredient_chain_state="NOT_EVALUATED",
                ),
            )
        except OSError:
            return ProvenanceEvidence(
                status=ProvenanceStatus.ERROR,
                provider=self.name,
                reason_codes=["C2PA_INSPECTION_EXECUTION_FAILED"],
                trust_details=self._trust_details(
                    manifest_present=None,
                    manifest_valid=None,
                    signature_valid=None,
                    signer_trusted=None,
                    ai_assertion_present=None,
                    ingredient_chain_state="NOT_EVALUATED",
                ),
            )

        absence_message = completed.stderr.strip().casefold()
        if completed.returncode != 0 and absence_message in {
            "error: no claim found",
            "error: no manifest found",
        }:
            return ProvenanceEvidence(
                status=ProvenanceStatus.NOT_PRESENT,
                provider=self.name,
                reason_codes=[
                    "C2PA_MANIFEST_NOT_PRESENT",
                    "ABSENCE_DOES_NOT_ESTABLISH_HUMAN_ORIGIN",
                ],
                trust_details=self._trust_details(
                    manifest_present=False,
                    manifest_valid=None,
                    signature_valid=None,
                    signer_trusted=None,
                    ai_assertion_present=None,
                    ingredient_chain_state="NOT_PRESENT",
                ),
            )
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError:
            if completed.returncode != 0:
                return ProvenanceEvidence(
                    status=ProvenanceStatus.ERROR,
                    provider=self.name,
                    reason_codes=["C2PA_OUTPUT_NOT_JSON", "C2PA_INSPECTION_FAILED"],
                    trust_details=self._trust_details(
                        manifest_present=None,
                        manifest_valid=None,
                        signature_valid=None,
                        signer_trusted=None,
                        ai_assertion_present=None,
                        ingredient_chain_state="NOT_EVALUATED",
                    ),
                )
            return ProvenanceEvidence(
                status=ProvenanceStatus.ERROR,
                provider=self.name,
                reason_codes=["C2PA_OUTPUT_NOT_JSON"],
                trust_details=self._trust_details(
                    manifest_present=None,
                    manifest_valid=None,
                    signature_valid=None,
                    signer_trusted=None,
                    ai_assertion_present=None,
                    ingredient_chain_state="NOT_EVALUATED",
                ),
            )

        if not isinstance(payload, dict):
            return ProvenanceEvidence(
                status=ProvenanceStatus.ERROR,
                provider=self.name,
                reason_codes=["C2PA_JSON_ROOT_NOT_OBJECT"],
                trust_details=self._trust_details(
                    manifest_present=None,
                    manifest_valid=None,
                    signature_valid=None,
                    signer_trusted=None,
                    ai_assertion_present=None,
                    ingredient_chain_state="NOT_EVALUATED",
                ),
            )
        if not payload:
            return ProvenanceEvidence(
                status=ProvenanceStatus.NOT_PRESENT,
                provider=self.name,
                reason_codes=[
                    "C2PA_MANIFEST_NOT_PRESENT",
                    "ABSENCE_DOES_NOT_ESTABLISH_HUMAN_ORIGIN",
                ],
                trust_details=self._trust_details(
                    manifest_present=False,
                    manifest_valid=None,
                    signature_valid=None,
                    signer_trusted=None,
                    ai_assertion_present=None,
                    ingredient_chain_state="NOT_PRESENT",
                ),
            )

        active_label, active_manifest = _active_manifest(payload)
        if active_label is None or active_manifest is None:
            return ProvenanceEvidence(
                status=ProvenanceStatus.INVALID,
                provider=self.name,
                reason_codes=["C2PA_MANIFEST_STRUCTURE_INVALID"],
                trust_details=self._trust_details(
                    manifest_present=True,
                    manifest_valid=False,
                    signature_valid=None,
                    signer_trusted=None,
                    ai_assertion_present=None,
                    ingredient_chain_state="MALFORMED",
                ),
            )

        summary = self._summary(payload)
        ingredients = active_manifest.get("ingredients")
        ingredient_chain_state = (
            "NOT_DECLARED"
            if "ingredients" not in active_manifest
            else "PRESENT"
            if isinstance(ingredients, list) and bool(ingredients)
            else "DECLARED_EMPTY"
            if isinstance(ingredients, list)
            else "MALFORMED"
        )
        validation_entries = _validation_entries(payload)
        normalized_codes = {code.casefold(): bucket for code, bucket in validation_entries}
        signature_mismatch = any(
            code.startswith("claimsignature.")
            and code not in {"claimsignature.validated", "claimsignature.valid"}
            for code in normalized_codes
        )
        explicitly_trusted = "signingcredential.trusted" in normalized_codes
        explicitly_untrusted = "signingcredential.untrusted" in normalized_codes
        non_trust_failures = [
            code
            for code, bucket in normalized_codes.items()
            if bucket == "failure"
            and code
            not in {
                "signingcredential.untrusted",
                "signingcredential.trusted",
            }
        ]
        nonzero_unexplained = bool(
            completed.returncode != 0
            and not (explicitly_untrusted and not non_trust_failures and not signature_mismatch)
        )
        invalid = bool(signature_mismatch or non_trust_failures or nonzero_unexplained)
        signature_validated = bool(
            "claimsignature.validated" in normalized_codes
            or "claimsignature.valid" in normalized_codes
            or (completed.returncode == 0 and not invalid)
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
        trust_details = self._trust_details(
            manifest_present=True,
            manifest_valid=not invalid,
            signature_valid=(
                False if signature_mismatch else True if signature_validated else None
            ),
            signer_trusted=(None if invalid else explicitly_trusted),
            ai_assertion_present=summary["ai_assertion_present"],
            ingredient_chain_state=ingredient_chain_state,
        )
        if not invalid and not explicitly_trusted:
            trust_details["signer_trusted"] = False
            trust_details["signer_trust_state"] = "NOT_CONFIRMED"
        return ProvenanceEvidence(
            status=state,
            provider=self.name,
            reason_codes=reasons,
            manifest_summary=summary,
            trust_details=trust_details,
        )


class ProvenanceRouter:
    def __init__(
        self,
        *,
        mode: str,
        binary: str,
        expected_version: str,
        expected_binary_sha256: str,
        timeout_seconds: int,
        trust_policy_id: str,
    ) -> None:
        official = C2PAToolProvenanceProvider(
            binary,
            timeout_seconds,
            trust_policy_id,
            expected_version,
            expected_binary_sha256,
        )
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
            "trust_policy_id": getattr(self.active, "trust_policy_id", None),
            "binary_path": getattr(self.active, "binary_path", None),
            "binary_version": getattr(self.active, "actual_version", None),
            "binary_sha256": getattr(self.active, "actual_binary_sha256", None),
            "expected_binary_version": getattr(self.active, "expected_version", None),
            "expected_binary_sha256": getattr(self.active, "expected_binary_sha256", None),
        }
