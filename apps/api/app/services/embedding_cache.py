from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np

from app.services.model_bundle import canonical_json_digest

EMBEDDING_CACHE_SCHEMAS = {
    "COPY": "creatorproof.visual_embedding.v2",
    "STYLE": "creatorproof.style_embedding.v2",
}


def bytes_sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _provider_status(provider) -> dict:
    status = getattr(provider, "status", None)
    if not callable(status):
        return {}
    value = status()
    return value if isinstance(value, dict) else {}


def provider_runtime_identity(
    container,
    provider,
    *,
    lane: str,
    source_sha256: str,
    dimensions: int | None = None,
) -> dict:
    if lane not in EMBEDDING_CACHE_SCHEMAS:
        raise ValueError(f"Unsupported embedding cache lane: {lane}")
    status = _provider_status(provider)
    primary = (
        status.get("primary_identity") if isinstance(status.get("primary_identity"), dict) else {}
    )
    artifact_sha256 = (
        status.get("artifact_sha256")
        or status.get("actual_artifact_sha256")
        or primary.get("artifact_sha256")
        or status.get("expected_artifact_sha256")
        or primary.get("expected_artifact_sha256")
        or getattr(provider, "artifact_sha256", None)
        or getattr(provider, "expected_sha256", None)
    )
    resolved_dimensions = dimensions or getattr(provider, "dimensions", None)
    if resolved_dimensions is None:
        raise ValueError("Embedding provider must declare dimensions before cache lookup")
    resolved_dimensions = int(resolved_dimensions)
    if resolved_dimensions <= 0:
        raise ValueError("Embedding dimensions must be positive")
    bundle = container.model_bundle
    identity = {
        "lane": lane,
        "provider": str(provider.name),
        "model_identity": str(
            getattr(provider, "model_identity", primary.get("model_identity") or provider.name)
        ),
        "artifact_sha256": str(artifact_sha256) if artifact_sha256 else None,
        "preprocessing_identity": str(
            getattr(
                provider,
                "preprocessing_identity",
                primary.get("preprocessing_identity") or "PROVIDER_DEFINED_PREPROCESSING",
            )
        ),
        "dimensions": resolved_dimensions,
        "source_sha256": source_sha256,
        "model_bundle_id": bundle.bundle_id,
        "model_bundle_manifest_digest_sha256": bundle.manifest_digest_sha256,
        "application_revision": bundle.application_revision,
    }
    return {
        **identity,
        "identity_digest_sha256": canonical_json_digest(identity),
    }


def cache_key(storage_key: str, provider_name: str, identity_digest: str, *, lane: str) -> str:
    if lane not in EMBEDDING_CACHE_SCHEMAS:
        raise ValueError(f"Unsupported embedding cache lane: {lane}")
    prefix = storage_key.rsplit("/", 1)[0]
    safe_provider = "".join(
        character if character.isalnum() or character in "-_" else "-"
        for character in provider_name
    )
    suffix = "visual" if lane == "COPY" else "style"
    return f"{prefix}/embeddings/{suffix}/{safe_provider}/{identity_digest}.json"


def encode_embedding(*, lane: str, identity: dict, vector: np.ndarray) -> bytes:
    normalized = np.asarray(vector, dtype=np.float32).reshape(-1)
    if normalized.shape[0] != int(identity["dimensions"]):
        raise ValueError("Embedding dimension does not match provider identity")
    if not np.isfinite(normalized).all():
        raise ValueError("Embedding contains non-finite values")
    norm = float(np.linalg.norm(normalized))
    if norm <= 1e-12:
        raise ValueError("Embedding norm is invalid")
    normalized = normalized / norm
    payload = {
        "schema": EMBEDDING_CACHE_SCHEMAS[lane],
        "identity": identity,
        "vector": [round(float(value), 8) for value in normalized],
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()


def decode_embedding(raw: bytes, *, lane: str, expected_identity: dict) -> np.ndarray:
    payload = json.loads(raw)
    if payload.get("schema") != EMBEDDING_CACHE_SCHEMAS[lane]:
        raise ValueError("Embedding cache schema mismatch")
    if payload.get("identity") != expected_identity:
        raise ValueError("Embedding cache identity mismatch")
    vector = np.asarray(payload.get("vector"), dtype=np.float32)
    if vector.ndim != 1 or vector.shape[0] != int(expected_identity["dimensions"]):
        raise ValueError("Embedding cache dimension mismatch")
    if not np.isfinite(vector).all():
        raise ValueError("Embedding cache contains non-finite values")
    norm = float(np.linalg.norm(vector))
    if norm <= 1e-12:
        raise ValueError("Embedding cache norm is invalid")
    return vector / norm


def source_identity(
    container, storage_key: str, declared_sha256: str | None
) -> tuple[str, bytes | None]:
    if declared_sha256:
        digest = str(declared_sha256).strip().lower()
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            raise ValueError("Declared source SHA-256 is invalid")
        return digest, None
    raw = container.storage.read(storage_key)
    return bytes_sha256(raw), raw


def cache_path_for_debug(container, key: str) -> Path:
    """Resolve a cache key for diagnostics without weakening object-store checks."""

    return (container.storage.root / key).resolve()
