"""Evidence Statement signing and key management.

The signer holds a service key. Private material comes from the environment or a
secret manager and is never written to the database; only the key id and public
key are persisted so historical statements stay verifiable after rotation.
"""

from __future__ import annotations

import base64
import hashlib
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.services import cose, crypto_ed25519
from app.services.canonical import canonicalize

logger = logging.getLogger("creatorproof.signing")


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _unb64(value: str) -> bytes:
    return base64.b64decode(value.encode("ascii"))


class StatementSigner:
    algorithm = "Ed25519"

    def __init__(self, *, kid: str, private_key_hex: str, fallback_material: str) -> None:
        self.kid = kid
        self.enabled = True
        if private_key_hex:
            try:
                seed = bytes.fromhex(private_key_hex.removeprefix("0x"))
            except ValueError as exc:
                raise ValueError(
                    "CREATORPROOF_STATEMENT_SIGNING_PRIVATE_KEY_HEX is not valid hex"
                ) from exc
            if len(seed) != 32:
                raise ValueError("Statement signing key must be a 32-byte Ed25519 seed")
            self.key_source = "CONFIGURED"
        else:
            # Deterministic development key so a restart does not invalidate the
            # statements produced by the previous process. Production configuration
            # refuses this path.
            seed = hashlib.sha256(f"creatorproof-dev-signing::{fallback_material}::{kid}".encode())
            seed = seed.digest()
            self.key_source = "DERIVED_DEVELOPMENT_KEY"
        self._seed = seed
        self.public_key = crypto_ed25519.public_key_from_seed(seed)

    @property
    def public_key_hex(self) -> str:
        return self.public_key.hex()

    def sign(self, payload: dict) -> dict:
        """Return the canonical digest plus a raw and COSE_Sign1 signature."""
        canonical = canonicalize(payload)
        digest = hashlib.sha256(canonical).hexdigest()
        protected = cose.protected_header()
        to_be_signed = cose.sig_structure(canonical, protected=protected)
        signature = crypto_ed25519.sign(self._seed, to_be_signed)
        envelope = cose.build_sign1(payload=canonical, signature=signature, kid=self.kid)
        return {
            "payload_digest_sha256": digest,
            "signature_alg": self.algorithm,
            "signature_kid": self.kid,
            "signature_b64": _b64(signature),
            "cose_sign1_b64": _b64(envelope),
            "public_key_hex": self.public_key_hex,
            "key_source": self.key_source,
        }

    def status(self) -> dict:
        return {
            "enabled": self.enabled,
            "kid": self.kid,
            "algorithm": self.algorithm,
            "public_key_hex": self.public_key_hex,
            "key_source": self.key_source,
        }


class DisabledSigner:
    algorithm = "none"
    kid = "unsigned"
    key_source = "DISABLED"
    enabled = False
    public_key_hex = ""

    def sign(self, payload: dict) -> dict:
        return {
            "payload_digest_sha256": hashlib.sha256(canonicalize(payload)).hexdigest(),
            "signature_alg": None,
            "signature_kid": None,
            "signature_b64": None,
            "cose_sign1_b64": None,
            "public_key_hex": "",
            "key_source": self.key_source,
        }

    def status(self) -> dict:
        return {
            "enabled": False,
            "kid": None,
            "algorithm": None,
            "public_key_hex": "",
            "key_source": self.key_source,
        }


def build_signer(settings):
    if not settings.statement_signing_enabled:
        return DisabledSigner()
    return StatementSigner(
        kid=settings.statement_signing_kid,
        private_key_hex=settings.statement_signing_private_key_hex,
        fallback_material=settings.api_key_pepper,
    )


def register_signing_key(db: Session, signer) -> None:
    """Persist public key metadata so historical statements verify after rotation."""
    if not getattr(signer, "enabled", False):
        return
    from app.models import SigningKey

    existing = db.scalar(select(SigningKey).where(SigningKey.kid == signer.kid))
    if existing is not None:
        if existing.public_key_hex != signer.public_key_hex:
            raise RuntimeError(
                f"Signing key id {signer.kid!r} is already bound to a different public key; "
                "rotate to a new kid instead of silently replacing trust history"
            )
        return
    db.add(
        SigningKey(
            kid=signer.kid,
            algorithm=signer.algorithm,
            public_key_hex=signer.public_key_hex,
            active=True,
        )
    )
    db.commit()


def verify_statement_signature(
    payload: dict,
    *,
    signature_b64: str | None,
    public_key_hex: str,
) -> bool:
    if not signature_b64 or not public_key_hex:
        return False
    try:
        canonical = canonicalize(payload)
        to_be_signed = cose.sig_structure(canonical, protected=cose.protected_header())
        return crypto_ed25519.verify(
            bytes.fromhex(public_key_hex), to_be_signed, _unb64(signature_b64)
        )
    except Exception:
        return False


def verify_cose_sign1(envelope_b64: str, public_key_hex: str) -> dict:
    """Verify a detached-key COSE_Sign1 envelope and return its parsed payload."""
    parsed = cose.parse_sign1(_unb64(envelope_b64))
    to_be_signed = cose.sig_structure(parsed["payload"], protected=parsed["protected"])
    valid = crypto_ed25519.verify(
        bytes.fromhex(public_key_hex), to_be_signed, bytes(parsed["signature"])
    )
    return {
        "valid": valid,
        "kid": parsed["kid"],
        "payload_bytes": parsed["payload"],
        "payload_digest_sha256": hashlib.sha256(parsed["payload"]).hexdigest(),
    }
