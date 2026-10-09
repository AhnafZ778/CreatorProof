import hashlib
import json
import os
import selectors
import shutil
import signal
import subprocess
import tempfile
import time
from pathlib import Path

from app.domain.enums import ProvenanceStatus
from app.providers.contracts import ProvenanceEvidence

_MAX_OUTPUT_BYTES = 8 * 1024 * 1024
_MAX_JSON_DEPTH = 20
_MAX_JSON_TOKENS = 50_000


class C2PAOutputLimitError(RuntimeError):
    """The subprocess exceeded its combined stdout/stderr capture budget."""


def _run_bounded(
    args: list[str], *, timeout: float, max_bytes: int = _MAX_OUTPUT_BYTES
) -> subprocess.CompletedProcess:
    """Drain both pipes in fixed chunks and kill at the limit, before allocation.

    The Linux deployment uses selectable pipes. stdout and stderr share one
    budget; no communicate()/capture_output path can buffer arbitrary output.
    A dedicated process group lets timeout/overflow cleanup terminate descendants
    that still hold an inherited pipe open, then reap the direct child.
    """
    captured = {"stdout": bytearray(), "stderr": bytearray()}
    count = 0
    deadline = time.monotonic() + timeout
    with subprocess.Popen(
        args,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=os.name == "posix",
    ) as process:
        try:
            with selectors.DefaultSelector() as selector:
                assert process.stdout is not None and process.stderr is not None
                selector.register(process.stdout, selectors.EVENT_READ, "stdout")
                selector.register(process.stderr, selectors.EVENT_READ, "stderr")
                while selector.get_map():
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise subprocess.TimeoutExpired(args, timeout)
                    for key, _mask in selector.select(min(remaining, 0.1)):
                        # At most one excess byte is read, and is never appended.
                        block = os.read(key.fd, min(64 * 1024, max_bytes - count + 1))
                        if not block:
                            selector.unregister(key.fileobj)
                            continue
                        if count + len(block) > max_bytes:
                            raise C2PAOutputLimitError("C2PA output capture limit exceeded")
                        captured[key.data].extend(block)
                        count += len(block)
                returncode = process.wait(timeout=max(0.001, deadline - time.monotonic()))
        except BaseException:
            if os.name == "posix":
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            elif process.poll() is None:
                process.kill()
            process.wait(timeout=5)
            raise
    return subprocess.CompletedProcess(
        args,
        returncode,
        captured["stdout"].decode("utf-8", errors="replace"),
        captured["stderr"].decode("utf-8", errors="replace"),
    )


def _json_within_budget(text: str) -> bool:
    """Reject excessive nesting/container tokens before JSON materialization."""
    depth = tokens = 0
    quoted = escaped = False
    for character in text:
        if quoted:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                quoted = False
            continue
        if character == '"':
            quoted = True
        elif character in "[{":
            depth += 1
            tokens += 1
        elif character in "]}":
            depth -= 1
        elif character in ",:":
            tokens += 1
        if depth > _MAX_JSON_DEPTH or tokens > _MAX_JSON_TOKENS:
            return False
    return True


def _scalar_text(value, limit: int) -> str | None:
    """Only scalar strings may enter a human-readable manifest projection."""
    return value[:limit] if isinstance(value, str) else None


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict:
    """Duplicate keys must not overwrite an earlier validation failure."""
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("C2PA JSON contains a duplicate object key")
        result[key] = value
    return result


def _bounded_json_integer(value: str) -> int:
    # Do not depend on Python's configurable global integer conversion limit.
    if len(value) > 128:
        raise ValueError("C2PA JSON integer is too long")
    return int(value)


def _reject_non_json_constant(value: str):
    raise ValueError(f"Non-JSON numeric constant: {value}")


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


def _walk(value, depth=0):
    if depth > 20:
        return
    if isinstance(value, dict):
        for key, item in value.items():
            yield str(key), item
            yield from _walk(item, depth + 1)
    elif isinstance(value, list):
        for item in value:
            yield from _walk(item, depth + 1)


def _active_manifest(payload: dict) -> tuple[str | None, dict | None]:
    active = payload.get("active_manifest") or payload.get("activeManifest")
    manifests = payload.get("manifests")
    if not isinstance(active, str) or not isinstance(manifests, dict):
        return None, None
    manifest = manifests.get(active)
    return active, manifest if isinstance(manifest, dict) else None


def _validation_entries(payload: dict) -> list[tuple[str, str]]:
    entries: list[tuple[str, str]] = []

    def visit(value, bucket: str, depth: int = 0) -> None:
        if depth > 20:
            return
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
                visit(item, next_bucket, depth + 1)
        elif isinstance(value, list):
            for item in value:
                visit(item, bucket, depth + 1)

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
            completed = _run_bounded(
                [self.binary_path, "--version"],
                timeout=min(self.timeout_seconds, 10),
                max_bytes=16 * 1024,
            )
        except C2PAOutputLimitError:
            return "C2PATOOL_IDENTITY_OUTPUT_OVERSIZED"
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
        actions = []
        model_names = set()
        for key, value in _walk(active_manifest.get("assertions") or []):
            if key == "actions" and isinstance(value, list):
                for action in value[:100]:
                    if not isinstance(action, dict):
                        continue
                    if len(actions) >= 100:
                        break
                    actions.append(
                        {
                            "action": _scalar_text(action.get("action"), 120) or "UNKNOWN",
                            "when": _scalar_text(action.get("when"), 80),
                            "digital_source_type": _scalar_text(
                                action.get("digitalSourceType"), 240
                            ),
                        }
                    )
            if (
                key in {"model", "modelName", "model_name"}
                and isinstance(value, str)
                and len(model_names) < 100
            ):
                model_names.add(value[:160])
        ingredients = []
        declared_ingredients = active_manifest.get("ingredients") or []
        for item in (declared_ingredients if isinstance(declared_ingredients, list) else [])[:100]:
            if not isinstance(item, dict):
                continue
            identifier = item.get("instance_id") or item.get("instanceID") or item.get("title")
            identifier = identifier if isinstance(identifier, str) else "unknown"
            reference = item.get("active_manifest") or item.get("c2pa_manifest")
            reference = reference if isinstance(reference, str) else None
            ingredients.append(
                {
                    "identifier_sha256": hashlib.sha256(identifier.encode()).hexdigest(),
                    "relationship": _scalar_text(item.get("relationship"), 120) or "INGREDIENT",
                    "manifest_reference_sha256": hashlib.sha256(reference.encode()).hexdigest()
                    if reference
                    else None,
                    "thumbnail_present": bool(item.get("thumbnail")),
                    "validation_status": "DECLARED_NOT_INDEPENDENTLY_VERIFIED",
                }
            )
        signature_info = active_manifest.get("signature_info")
        signature_info = signature_info if isinstance(signature_info, dict) else {}
        claim_version = active_manifest.get("claim_version")
        return {
            "active_manifest": _scalar_text(active, 512),
            "claim_generator": _scalar_text(
                active_manifest.get("claim_generator") or active_manifest.get("claimGenerator"), 240
            ),
            "ai_source_markers": ai_markers,
            "ai_assertion_present": bool(ai_markers),
            "actions": actions,
            "creation_actions": [item for item in actions if item["action"] == "c2pa.created"],
            "editing_actions": [item for item in actions if item["action"] != "c2pa.created"],
            "model_names": sorted(model_names),
            "ingredients": ingredients,
            "thumbnail_present": bool(active_manifest.get("thumbnail")),
            "manifest_repository_identifier_sha256": hashlib.sha256(active.encode()).hexdigest()
            if active
            else None,
            "signature_timestamp": _scalar_text(signature_info.get("time"), 80),
            "c2pa_version": claim_version
            if type(claim_version) is int
            else _scalar_text(claim_version, 40),
            "validation_codes": sorted({code[:240] for code, _bucket in validation_entries}),
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
            # Local read-only inspection may not fetch URLs embedded by an
            # untrusted uploader (remote manifests, OCSP). Trust remains separate.
            with tempfile.TemporaryDirectory(prefix="creatorproof-c2pa-") as directory:
                settings = Path(directory) / "settings.json"
                settings.write_text(
                    json.dumps(
                        {
                            "verify": {
                                "remote_manifest_fetch": False,
                                "ocsp_fetch": False,
                                "verify_after_reading": True,
                            }
                        }
                    )
                )
                completed = _run_bounded(
                    [
                        str(self.binary_path),
                        "--settings",
                        str(settings),
                        "--detailed",
                        str(Path(source_path).resolve()),
                    ],
                    timeout=self.timeout_seconds,
                )
        except C2PAOutputLimitError:
            return ProvenanceEvidence(
                status=ProvenanceStatus.ERROR,
                provider=self.name,
                reason_codes=["C2PA_OUTPUT_OVERSIZED"],
                trust_details=self._trust_details(
                    manifest_present=None,
                    manifest_valid=None,
                    signature_valid=None,
                    signer_trusted=None,
                    ai_assertion_present=None,
                    ingredient_chain_state="NOT_EVALUATED",
                ),
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
        if not _json_within_budget(completed.stdout):
            return ProvenanceEvidence(
                status=ProvenanceStatus.ERROR,
                provider=self.name,
                reason_codes=["C2PA_JSON_STRUCTURE_LIMIT"],
                trust_details=self._trust_details(
                    manifest_present=None,
                    manifest_valid=None,
                    signature_valid=None,
                    signer_trusted=None,
                    ai_assertion_present=None,
                    ingredient_chain_state="NOT_EVALUATED",
                ),
            )
        if completed.returncode != 0 and any(
            token in absence_message
            for token in (
                "unsupported",
                "not supported",
                "unrecognized file type",
            )
        ):
            return ProvenanceEvidence(
                status=ProvenanceStatus.NOT_CHECKED,
                provider=self.name,
                reason_codes=["C2PA_FORMAT_UNSUPPORTED"],
            )
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
            payload = json.loads(
                completed.stdout,
                object_pairs_hook=_unique_json_object,
                parse_int=_bounded_json_integer,
                parse_constant=_reject_non_json_constant,
            )
        except (ValueError, RecursionError):
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
        normalized_codes = {}
        for code, bucket in validation_entries:
            normalized = code.casefold()
            # Duplicate display entries cannot erase a recorded failure.
            if normalized not in normalized_codes or bucket == "failure":
                normalized_codes[normalized] = bucket
        signature_mismatch = any(
            code.startswith("claimsignature.")
            and (
                bucket == "failure"
                or code
                not in {
                    "claimsignature.validated",
                    "claimsignature.valid",
                    "claimsignature.insidevalidity",
                }
            )
            for code, bucket in normalized_codes.items()
        )
        explicitly_untrusted = "signingcredential.untrusted" in normalized_codes
        trust_contradictory = (
            "signingcredential.trusted" in normalized_codes and explicitly_untrusted
        )
        explicitly_trusted = (
            "signingcredential.trusted" in normalized_codes
            and normalized_codes["signingcredential.trusted"] != "failure"
            and not trust_contradictory
        )
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
        if trust_contradictory:
            reasons.append("C2PA_SIGNER_TRUST_RESULTS_CONTRADICTORY")
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
