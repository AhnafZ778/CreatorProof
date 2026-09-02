"""Generate one coherent set of deployment secrets without writing them to disk.

Run locally and copy each value directly into the matching Render/Vercel secret.
The output is intentionally sensitive and must never be committed or pasted into
build logs.
"""

from __future__ import annotations

import hashlib
import os
import secrets

from app.core.security import generate_api_key
from app.services.crypto_ed25519 import public_key_from_seed


def main() -> int:
    pepper = secrets.token_urlsafe(48)
    api_key = generate_api_key(pepper).secret
    signing_seed = os.urandom(32)
    signing_fingerprint = hashlib.sha256(public_key_from_seed(signing_seed)).hexdigest()
    values = {
        "CREATORPROOF_API_KEY_PEPPER": pepper,
        # Put this same value in Render's CREATORPROOF_BOOTSTRAP_API_KEY and
        # Vercel's CREATORPROOF_API_KEY.
        "CREATORPROOF_BOOTSTRAP_API_KEY": api_key,
        "CREATORPROOF_RUNTIME_DATABASE_PASSWORD": secrets.token_urlsafe(40),
        "CREATORPROOF_STATEMENT_SIGNING_PRIVATE_KEY_HEX": signing_seed.hex(),
        "CREATORPROOF_TRUSTED_ISSUER_KEY_SHA256": signing_fingerprint,
        "CREATORPROOF_UPLOAD_TOKEN_SECRET": secrets.token_urlsafe(48),
    }
    for key, value in values.items():
        print(f"{key}={value}")
    print(f"CREATORPROOF_API_KEY={api_key}")
    print(f"NEXT_PUBLIC_CREATORPROOF_ISSUER_KEY_FINGERPRINT_SHA256={signing_fingerprint}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
