"""Short-lived, tenant-bound grants for direct object uploads.

The browser receives a presigned object-store request, but it never receives the
backend API key.  This signed token is the link between that temporary object and
the authenticated scan or registration request that consumes it.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from typing import Literal

from app.services.storage import ObjectStore

UploadPurpose = Literal["scan", "work"]


class UploadGrantError(ValueError):
    """A safe, client-facing direct-upload validation failure."""

    def __init__(self, code: str, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class UploadGrantClaims:
    tenant_id: str
    purpose: UploadPurpose
    key: str
    filename: str
    content_type: str
    size_bytes: int
    expires_at: int
    nonce: str


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    if not value or len(value) > 8192:
        raise ValueError("Invalid base64 value")
    padding = "=" * (-len(value) % 4)
    return base64.b64decode(value + padding, altchars=b"-_", validate=True)


def _sign(secret: str, payload: bytes) -> bytes:
    if len(secret.encode("utf-8")) < 32:
        raise ValueError("The upload token secret must contain at least 32 bytes")
    return hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).digest()


def issue_upload_token(
    secret: str,
    *,
    tenant_id: str,
    purpose: UploadPurpose,
    key: str,
    filename: str,
    content_type: str,
    size_bytes: int,
    ttl_seconds: int,
    now: int | None = None,
    nonce: str | None = None,
) -> tuple[str, UploadGrantClaims]:
    """Issue an opaque-looking HMAC token and return its validated claims."""

    issued_at = int(time.time()) if now is None else int(now)
    claims = UploadGrantClaims(
        tenant_id=tenant_id,
        purpose=purpose,
        key=key,
        filename=filename,
        content_type=content_type,
        size_bytes=size_bytes,
        expires_at=issued_at + ttl_seconds,
        nonce=nonce or secrets.token_urlsafe(18),
    )
    payload = json.dumps(
        {
            "v": 1,
            "tenant_id": claims.tenant_id,
            "purpose": claims.purpose,
            "key": claims.key,
            "filename": claims.filename,
            "content_type": claims.content_type,
            "size_bytes": claims.size_bytes,
            "expires_at": claims.expires_at,
            "nonce": claims.nonce,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"{_b64encode(payload)}.{_b64encode(_sign(secret, payload))}", claims


def verify_upload_token(
    token: str,
    secret: str,
    *,
    tenant_id: str,
    purpose: UploadPurpose,
    now: int | None = None,
) -> UploadGrantClaims:
    """Verify signature, expiry, purpose, tenant and server-generated key scope."""

    invalid = UploadGrantError(
        "UPLOAD_TOKEN_INVALID",
        "The upload token is invalid, expired, or belongs to another request.",
        status_code=401,
    )
    try:
        encoded_payload, encoded_signature = token.split(".", 1)
        payload = _b64decode(encoded_payload)
        signature = _b64decode(encoded_signature)
        if not hmac.compare_digest(signature, _sign(secret, payload)):
            raise invalid
        data = json.loads(payload)
        if not isinstance(data, dict) or data.get("v") != 1:
            raise invalid
        claims = UploadGrantClaims(
            tenant_id=str(data["tenant_id"]),
            purpose=data["purpose"],
            key=str(data["key"]),
            filename=str(data["filename"]),
            content_type=str(data["content_type"]),
            size_bytes=int(data["size_bytes"]),
            expires_at=int(data["expires_at"]),
            nonce=str(data["nonce"]),
        )
    except UploadGrantError:
        raise
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise invalid from exc

    current_time = int(time.time()) if now is None else int(now)
    expected_prefix = f"incoming/{tenant_id}/{purpose}/"
    if (
        claims.tenant_id != tenant_id
        or claims.purpose != purpose
        or claims.expires_at <= current_time
        or claims.size_bytes <= 0
        or not claims.nonce
        or not claims.key.startswith(expected_prefix)
        or ".." in claims.key.split("/")
    ):
        raise invalid
    return claims


def load_verified_upload(
    storage: ObjectStore,
    claims: UploadGrantClaims,
    *,
    max_bytes: int,
) -> bytes:
    """Read only an object whose signed size, type and metadata still match."""

    metadata = storage.head(claims.key)
    if metadata is None:
        raise UploadGrantError(
            "UPLOAD_NOT_FOUND",
            "The uploaded object was not found. Upload the image again.",
            status_code=404,
        )
    actual_size = int(metadata["size_bytes"])
    if actual_size != claims.size_bytes or actual_size > max_bytes:
        storage.delete(claims.key)
        raise UploadGrantError(
            "UPLOAD_SIZE_MISMATCH",
            "The uploaded object size does not match its grant.",
            status_code=413,
        )
    actual_content_type = (metadata.get("content_type") or "").split(";", 1)[0].lower()
    if actual_content_type != claims.content_type.lower():
        storage.delete(claims.key)
        raise UploadGrantError(
            "UPLOAD_TYPE_MISMATCH",
            "The uploaded object type does not match its grant.",
            status_code=415,
        )

    signed_metadata = {str(k).lower(): str(v) for k, v in metadata.get("metadata", {}).items()}
    expected_metadata = {
        "creatorproof-purpose": claims.purpose,
        "creatorproof-tenant": claims.tenant_id,
        "creatorproof-upload-nonce": claims.nonce,
        "creatorproof-size-bytes": str(claims.size_bytes),
    }
    if any(signed_metadata.get(key) != value for key, value in expected_metadata.items()):
        storage.delete(claims.key)
        raise UploadGrantError(
            "UPLOAD_METADATA_MISMATCH",
            "The uploaded object metadata does not match its grant.",
            status_code=400,
        )

    raw = storage.read_bytes(claims.key)
    if len(raw) != claims.size_bytes:
        storage.delete(claims.key)
        raise UploadGrantError(
            "UPLOAD_SIZE_MISMATCH",
            "The uploaded object changed while it was being verified.",
            status_code=409,
        )
    return raw
