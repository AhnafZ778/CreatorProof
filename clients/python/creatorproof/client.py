"""CreatorProof API client."""

from __future__ import annotations

import hashlib
import hmac
import json
import mimetypes
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_BASE_URL = "http://localhost:8000"
TERMINAL_STATES = {"COMPLETED", "FAILED", "CANCELLED"}
PUBLIC_CHAIN_SCOPES = {
    "PUBLIC_EVM_ATTESTATION",
    "PUBLIC_EVM_ATTESTATION_PACKET_HASH_ONLY",
    "EAS_ATTESTATION",
    "EVM_ATTESTATION",
}


class CreatorProofError(RuntimeError):
    """An API call failed. Carries the status and the server's own detail."""

    def __init__(self, status: int, detail: str, body: Any = None) -> None:
        super().__init__(f"CreatorProof API error {status}: {detail}")
        self.status = status
        self.detail = detail
        self.body = body


@dataclass(frozen=True)
class Work:
    id: str
    catalog_id: str
    title: str
    sha256: str
    rights_path: str
    raw: dict = field(repr=False, default_factory=dict)


@dataclass(frozen=True)
class ProofReceipt:
    anchor_status: str
    provider: str | None
    commitment_scope: str | None
    packet_hash_sha256: str | None
    receipt: dict | None = field(repr=False, default=None)
    proof_kind: str | None = None
    anchor_scope: str | None = None

    @property
    def is_public_blockchain(self) -> bool:
        """True only when proof kind / receipt scope identifies a public chain.

        ``commitment_scope`` describes which bytes were hashed and is not a
        blockchain discriminator.
        """
        receipt = self.receipt if isinstance(self.receipt, dict) else {}
        candidates = (
            self.proof_kind,
            self.anchor_scope,
            receipt.get("proof_kind"),
            receipt.get("anchor_scope"),
        )
        return any(
            isinstance(value, str) and value.strip().upper() in PUBLIC_CHAIN_SCOPES
            for value in candidates
        )

    @property
    def explorer_urls(self) -> dict[str, str]:
        """Normalized, HTTP(S)-only explorer URLs from legacy or structured receipts."""
        receipt = self.receipt if isinstance(self.receipt, dict) else {}
        candidates: list[tuple[str, Any]] = [("explorer", receipt.get("explorer_url"))]
        for container_value in (receipt.get("explorer"), receipt.get("explorer_urls")):
            if isinstance(container_value, str):
                candidates.append(("explorer", container_value))
                continue
            if not isinstance(container_value, dict):
                continue
            candidates.extend(
                [
                    (
                        "transaction",
                        container_value.get("transaction_url")
                        or container_value.get("transaction"),
                    ),
                    (
                        "attestation",
                        container_value.get("attestation_url")
                        or container_value.get("attestation"),
                    ),
                    (
                        "attester",
                        container_value.get("attester_url")
                        or container_value.get("address_url"),
                    ),
                    ("explorer", container_value.get("url")),
                ]
            )
        normalized: dict[str, str] = {}
        for kind, value in candidates:
            if not isinstance(value, str):
                continue
            parsed = urllib.parse.urlsplit(value)
            if parsed.scheme in {"http", "https"} and parsed.netloc:
                normalized.setdefault(kind, value)
        return normalized


@dataclass(frozen=True)
class ScanResult:
    id: str
    state: str
    match_status: str | None
    policy_action: str | None
    rights_path: str | None
    coverage_status: str | None
    raw: dict = field(repr=False, default_factory=dict)

    @property
    def evidence_packet(self) -> dict:
        packet = self.raw.get("evidence_packet")
        return packet if isinstance(packet, dict) else {}

    @property
    def proof(self) -> ProofReceipt:
        proof = self.evidence_packet.get("proof") or {}
        receipt = proof.get("receipt") if isinstance(proof, dict) else None
        receipt = receipt if isinstance(receipt, dict) else None
        return ProofReceipt(
            anchor_status=str(proof.get("anchor_status") or "UNKNOWN"),
            provider=proof.get("provider"),
            commitment_scope=proof.get("commitment_scope"),
            packet_hash_sha256=proof.get("packet_hash_sha256"),
            receipt=receipt,
            proof_kind=proof.get("proof_kind"),
            anchor_scope=proof.get("anchor_scope"),
        )

    @property
    def coverage_is_complete(self) -> bool:
        """A clean result over incomplete coverage proves nothing; check this first."""
        return self.coverage_status == "COMPLETE"


@dataclass(frozen=True)
class StageTimeline:
    scan_id: str
    lifecycle_state: str
    correlation_id: str | None
    stages: list[dict]


@dataclass(frozen=True)
class ReviewCase:
    id: str
    scan_id: str
    state: str
    priority: str | None
    assignee: str | None
    raw: dict = field(repr=False, default_factory=dict)


@dataclass(frozen=True)
class VerificationPackage:
    payload: dict

    def save(self, path: str | Path) -> Path:
        target = Path(path)
        target.write_text(json.dumps(self.payload, indent=2), encoding="utf-8")
        return target

    @property
    def proof_binding(self) -> dict:
        binding = self.payload.get("proof_binding")
        return binding if isinstance(binding, dict) else {}

    @property
    def bundled_issuer_key_fingerprint_sha256(self) -> str | None:
        """Compute the issuer-key fingerprint from the package's bundled raw key.

        This is an identifier, not a trust decision. Callers must compare it to
        a value obtained outside this package.
        """
        signature = self.payload.get("signature")
        trust_bundle = self.payload.get("trust_bundle")
        if not isinstance(signature, dict) or not isinstance(trust_bundle, dict):
            return None
        kid = signature.get("kid")
        keys = trust_bundle.get("keys")
        if not isinstance(kid, str) or not isinstance(keys, list):
            return None
        key = next(
            (
                candidate
                for candidate in keys
                if isinstance(candidate, dict) and candidate.get("kid") == kid
            ),
            None,
        )
        if not isinstance(key, dict) or not isinstance(key.get("public_key_hex"), str):
            return None
        try:
            raw = bytes.fromhex(key["public_key_hex"].removeprefix("0x"))
        except ValueError:
            return None
        if len(raw) != 32:
            return None
        return hashlib.sha256(raw).hexdigest()

    def matches_pinned_issuer_key(self, expected_fingerprint_sha256: str) -> bool:
        """Compare against a fingerprint supplied independently by the caller."""
        expected = (
            expected_fingerprint_sha256.strip()
            .lower()
            .removeprefix("sha256:")
            .removeprefix("0x")
        )
        actual = self.bundled_issuer_key_fingerprint_sha256
        return (
            len(expected) == 64
            and all(char in "0123456789abcdef" for char in expected)
            and actual is not None
            and hmac.compare_digest(actual, expected)
        )

    @property
    def live_chain_status(self) -> str:
        """A downloaded package cannot establish current EAS state by itself."""
        return "UNVERIFIED_OFFLINE"


def _encode_multipart(
    fields: dict[str, str], files: dict[str, tuple[str, bytes]]
) -> tuple[bytes, str]:
    boundary = f"----creatorproof{uuid.uuid4().hex}"
    parts: list[bytes] = []
    for name, value in fields.items():
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n'
            f"{value}\r\n".encode()
        )
    for name, (filename, content) in files.items():
        media_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        header = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
            f"Content-Type: {media_type}\r\n\r\n"
        ).encode()
        parts.extend([header, content, b"\r\n"])
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


class CreatorProofClient:
    """Synchronous client.

    ``correlation_id`` is echoed into API logs, scan records, statements and
    webhook deliveries, so one identifier follows a request through the whole
    system when a customer needs to trace it.
    """

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 30.0,
        correlation_id: str | None = None,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.correlation_id = correlation_id

    # -- transport ---------------------------------------------------------

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: bytes | None = None,
        content_type: str | None = None,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> Any:
        request = urllib.request.Request(f"{self.base_url}{path}", data=body, method=method)
        request.add_header("X-API-Key", self.api_key)
        request.add_header("Accept", "application/json")
        if content_type:
            request.add_header("Content-Type", content_type)
        if self.correlation_id:
            request.add_header("X-Correlation-Id", self.correlation_id)
        for key, value in (headers or {}).items():
            request.add_header(key, value)
        try:
            with urllib.request.urlopen(request, timeout=timeout or self.timeout) as response:
                raw = response.read().decode("utf-8")
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            try:
                parsed = json.loads(raw)
                detail = str(parsed.get("detail", raw))
            except json.JSONDecodeError:
                parsed, detail = None, raw
            raise CreatorProofError(exc.code, detail, parsed) from exc
        except urllib.error.URLError as exc:
            raise CreatorProofError(0, f"The API is unreachable: {exc.reason}") from exc

    def _get(self, path: str, **kwargs: Any) -> Any:
        return self._request("GET", path, **kwargs)

    def _post_json(self, path: str, payload: dict, **kwargs: Any) -> Any:
        return self._request(
            "POST",
            path,
            body=json.dumps(payload).encode("utf-8"),
            content_type="application/json",
            **kwargs,
        )

    # -- health ------------------------------------------------------------

    def health(self) -> dict:
        return self._get("/healthz")

    def readiness(self) -> dict:
        """Readiness reports degraded capabilities honestly; check before a demo."""
        return self._get("/readyz")

    # -- works -------------------------------------------------------------

    def register_work(
        self,
        image_path: str | Path,
        *,
        title: str,
        catalog_id: str,
        rights_path: str = "NO_LICENSE_INFO",
        allowed_uses: list[str] | None = None,
        claimant: str | None = None,
        claim_state: str = "ASSERTED",
    ) -> Work:
        path = Path(image_path)
        fields = {
            "title": title,
            "catalog_id": catalog_id,
            "rights_path": rights_path,
            "allowed_uses": json.dumps(allowed_uses or []),
            "claim_state": claim_state,
        }
        if claimant:
            fields["claimant"] = claimant
        body, content_type = _encode_multipart(fields, {"file": (path.name, path.read_bytes())})
        payload = self._request("POST", "/v1/works", body=body, content_type=content_type)
        return Work(
            id=payload["id"],
            catalog_id=payload["catalog_id"],
            title=payload["title"],
            sha256=payload["sha256"],
            rights_path=payload["rights_path"],
            raw=payload,
        )

    def bulk_import(
        self, catalog_id: str, entries: list[dict], *, timeout: float | None = None
    ) -> dict:
        """Import many works at once.

        Each entry needs a ``path`` plus optional ``title``, ``rights_path``,
        ``allowed_uses``, ``claimant`` and ``claim_state``. The response reports
        per-file outcomes; a partial import is normal and is never hidden.
        """
        manifest = [
            {**{key: value for key, value in entry.items() if key != "path"},
             "filename": Path(entry["path"]).name}
            for entry in entries
        ]
        # Every file shares the `files` field name, so the multipart body is built
        # directly rather than through a dict that would collapse the repeats.
        boundary = f"----creatorproof{uuid.uuid4().hex}"
        parts: list[bytes] = []
        for name, value in {"catalog_id": catalog_id, "manifest": json.dumps(manifest)}.items():
            parts.append(
                f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n'
                f"{value}\r\n".encode()
            )
        for entry in entries:
            path = Path(entry["path"])
            media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            parts.append(
                (
                    f"--{boundary}\r\n"
                    f'Content-Disposition: form-data; name="files"; filename="{path.name}"\r\n'
                    f"Content-Type: {media_type}\r\n\r\n"
                ).encode()
            )
            parts.extend([path.read_bytes(), b"\r\n"])
        parts.append(f"--{boundary}--\r\n".encode())
        return self._request(
            "POST",
            "/v1/works/bulk",
            body=b"".join(parts),
            content_type=f"multipart/form-data; boundary={boundary}",
            timeout=timeout or max(self.timeout, 120.0),
        )

    def list_works(self, catalog_id: str | None = None) -> list[dict]:
        suffix = f"?catalog_id={catalog_id}" if catalog_id else ""
        return self._get(f"/v1/works{suffix}")

    def delete_work(self, work_id: str) -> dict:
        """Delete a work and receive a deletion receipt listing what was removed."""
        return self._request("DELETE", f"/v1/works/{work_id}")

    # -- scans -------------------------------------------------------------

    def create_scan(
        self,
        image_path: str | Path,
        *,
        catalog_id: str,
        intended_use: str,
        idempotency_key: str | None = None,
    ) -> ScanResult:
        path = Path(image_path)
        body, content_type = _encode_multipart(
            {"catalog_id": catalog_id, "intended_use": intended_use},
            {"file": (path.name, path.read_bytes())},
        )
        payload = self._request(
            "POST",
            "/v1/scans",
            body=body,
            content_type=content_type,
            headers={"Idempotency-Key": idempotency_key or str(uuid.uuid4())},
        )
        return self._scan(payload)

    def get_scan(self, scan_id: str) -> ScanResult:
        return self._scan(self._get(f"/v1/scans/{scan_id}"))

    def wait_for_scan(
        self, scan_id: str, *, timeout: float = 180.0, poll_interval: float = 1.0
    ) -> ScanResult:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            result = self.get_scan(scan_id)
            if result.state in TERMINAL_STATES:
                return result
            time.sleep(poll_interval)
        raise CreatorProofError(0, f"Scan {scan_id} did not finish within {timeout:.0f}s")

    def cancel_scan(self, scan_id: str, reason: str) -> ScanResult:
        return self._scan(self._post_json(f"/v1/scans/{scan_id}/cancel", {"reason": reason}))

    def scan_stages(self, scan_id: str) -> StageTimeline:
        payload = self._get(f"/v1/scans/{scan_id}/stages")
        return StageTimeline(
            scan_id=payload["scan_id"],
            lifecycle_state=payload["lifecycle_state"],
            correlation_id=payload.get("correlation_id"),
            stages=payload.get("stages") or [],
        )

    @staticmethod
    def _scan(payload: dict) -> ScanResult:
        packet = payload.get("evidence_packet") or {}
        scope = packet.get("scope") or {} if isinstance(packet, dict) else {}
        return ScanResult(
            id=payload["id"],
            state=payload.get("state", "UNKNOWN"),
            match_status=payload.get("match_status"),
            policy_action=payload.get("policy_action"),
            rights_path=payload.get("rights_path"),
            coverage_status=scope.get("coverage_status"),
            raw=payload,
        )

    # -- statements and proof ---------------------------------------------

    def get_statement(self, scan_id: str) -> dict:
        return self._get(f"/v1/scans/{scan_id}/statement")

    def verify_statement(self, scan_id: str) -> dict:
        """Server-side verification. For an independent check use the package."""
        return self._get(f"/v1/scans/{scan_id}/statement/verify")

    def verification_package(self, scan_id: str) -> VerificationPackage:
        return VerificationPackage(self._get(f"/v1/scans/{scan_id}/verification-package"))

    def append_statement_status(self, scan_id: str, statement_type: str, reason: str) -> dict:
        """Record a correction, dispute, supersession or revocation.

        History is never rewritten: this appends a new signed statement that
        refers to the original.
        """
        return self._post_json(
            f"/v1/scans/{scan_id}/statement/status",
            {"statement_type": statement_type, "reason": reason},
        )

    def proof_status(self) -> dict:
        return self._get("/v1/proof/status")

    def verify_attestation(
        self,
        attestation_uid: str,
        *,
        expected_packet_hash_sha256: str | None = None,
    ) -> dict:
        """Verify a UID and, when supplied, bind it to the expected packet hash."""
        suffix = ""
        if expected_packet_hash_sha256 is not None:
            normalized = expected_packet_hash_sha256.removeprefix("0x")
            if len(normalized) != 64 or any(
                char not in "0123456789abcdefABCDEF" for char in normalized
            ):
                raise ValueError(
                    "expected_packet_hash_sha256 must be a 32-byte hexadecimal SHA-256 value"
                )
            suffix = "?" + urllib.parse.urlencode(
                {"expected_packet_hash_sha256": expected_packet_hash_sha256}
            )
        uid = urllib.parse.quote(attestation_uid, safe="")
        return self._get(f"/v1/proof/attestations/{uid}{suffix}")

    def trust_bundle(self) -> dict:
        return self._get("/v1/proof/trust-bundle")

    def transparency_checkpoint(self) -> dict:
        return self._get("/v1/proof/transparency/checkpoint")

    # -- rights, policy, review, webhooks ----------------------------------

    def create_party(self, payload: dict) -> dict:
        return self._post_json("/v1/parties", payload)

    def create_claim(self, payload: dict) -> dict:
        return self._post_json("/v1/claims", payload)

    def create_license(self, payload: dict) -> dict:
        return self._post_json("/v1/licenses", payload)

    def rights_position(self, work_id: str) -> dict:
        return self._get(f"/v1/rights/position?work_id={work_id}")

    def create_policy_version(self, payload: dict) -> dict:
        return self._post_json("/v1/policies", payload)

    def policy_dry_run(self, payload: dict) -> dict:
        """Evaluate policy versions against a scan without changing the record."""
        return self._post_json("/v1/policies/dry-run", payload)

    def list_review_cases(self, state: str | None = None) -> list[ReviewCase]:
        suffix = f"?state={state}" if state else ""
        return [
            ReviewCase(
                id=row["id"],
                scan_id=row["scan_id"],
                state=row["state"],
                priority=row.get("priority"),
                assignee=row.get("assignee"),
                raw=row,
            )
            for row in self._get(f"/v1/review-cases{suffix}")
        ]

    def get_review_case(self, case_id: str) -> dict:
        return self._get(f"/v1/review-cases/{case_id}")

    def append_review_action(self, case_id: str, payload: dict) -> dict:
        return self._post_json(f"/v1/review-cases/{case_id}/actions", payload)

    def create_webhook_endpoint(self, url: str, event_types: list[str]) -> dict:
        """Create a subscription. The signing secret is returned exactly once."""
        return self._post_json("/v1/webhooks/endpoints", {"url": url, "event_types": event_types})

    def list_webhook_deliveries(self, endpoint_id: str | None = None) -> list[dict]:
        suffix = f"?endpoint_id={endpoint_id}" if endpoint_id else ""
        return self._get(f"/v1/webhooks/deliveries{suffix}")

    def create_credential(self, payload: dict) -> dict:
        """Create an API credential. The secret is shown once and never stored."""
        return self._post_json("/v1/credentials", payload)


def verify_webhook_signature(
    *,
    secret: str,
    signature_header: str,
    timestamp_header: str,
    body: bytes,
    tolerance_seconds: int = 300,
) -> bool:
    """Verify an inbound CreatorProof webhook.

    The signature covers ``timestamp.body``, so a captured delivery cannot be
    replayed outside the tolerance window with a still-valid signature.
    """
    try:
        sent_at = int(timestamp_header)
    except (TypeError, ValueError):
        return False
    if abs(int(time.time()) - sent_at) > tolerance_seconds:
        return False
    expected = hmac.new(
        secret.encode("utf-8"), f"{sent_at}.".encode() + body, hashlib.sha256
    ).hexdigest()
    presented = signature_header.split("=", 1)[-1].strip()
    return hmac.compare_digest(expected, presented)
