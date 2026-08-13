import hashlib
import json


def normalize_scan_text(value: str) -> str:
    return value.strip()


def scan_request_digest(
    *,
    candidate_sha256: str,
    catalog_id: str,
    intended_use: str,
) -> str:
    """Bind an idempotency key to the material request fields already persisted on Scan."""
    material = {
        "schema": "creatorproof.scan_request.v1",
        "candidate_sha256": candidate_sha256.lower(),
        "catalog_id": normalize_scan_text(catalog_id),
        "intended_use": normalize_scan_text(intended_use),
    }
    encoded = json.dumps(material, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()
