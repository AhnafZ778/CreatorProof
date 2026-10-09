import hashlib
import json


def normalize_scan_text(value: str) -> str:
    return value.strip()


def scan_request_digest(
    *,
    candidate_sha256: str,
    catalog_id: str,
    intended_use: str,
    country_code: str | None = None,
    use_context: dict | None = None,
    source_url: str | None = None,
) -> str:
    """Bind an idempotency key to the material request fields already persisted on Scan."""
    material = {
        "schema": "creatorproof.scan_request.v1",
        "candidate_sha256": candidate_sha256.lower(),
        "catalog_id": normalize_scan_text(catalog_id),
        "intended_use": normalize_scan_text(intended_use),
    }
    # Keep the v1 digest unchanged for legacy clients that omit these fields.
    if country_code:
        material["submission_country_code"] = country_code.strip().upper()
    if use_context:
        material["use_context"] = use_context
    if source_url:
        material["submission_source_url"] = source_url
    encoded = json.dumps(material, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()
