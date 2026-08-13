from __future__ import annotations

from io import BytesIO

import numpy as np
from PIL import Image

from app.services.embedding_cache import (
    cache_key,
    decode_embedding,
    encode_embedding,
    provider_runtime_identity,
    source_identity,
)
from app.services.runtime_telemetry import increment_counter


def embedding_key(storage_key: str, provider_name: str, identity_digest: str) -> str:
    return cache_key(storage_key, provider_name, identity_digest, lane="COPY")


def persist_reference_embedding(
    container,
    storage_key: str,
    image: Image.Image,
    *,
    vector: np.ndarray | None = None,
    source_sha256: str | None = None,
) -> str | None:
    provider = container.ai_retrieval
    if not provider.available:
        return None
    vector = provider.embed(image) if vector is None else vector
    digest, _ = source_identity(container, storage_key, source_sha256)
    identity = provider_runtime_identity(
        container,
        provider,
        lane="COPY",
        source_sha256=digest,
        dimensions=int(vector.shape[0]),
    )
    key = embedding_key(storage_key, provider.name, identity["identity_digest_sha256"])
    container.storage.put(key, encode_embedding(lane="COPY", identity=identity, vector=vector))
    return key


def reference_embedding(
    container, storage_key: str, *, source_sha256: str | None = None
) -> np.ndarray | None:
    provider = container.ai_retrieval
    if not provider.available:
        return None
    digest, raw = source_identity(container, storage_key, source_sha256)
    if getattr(provider, "dimensions", None) is None:
        raw = container.storage.read(storage_key) if raw is None else raw
        with Image.open(BytesIO(raw)) as opened:
            image = opened.convert("RGB")
            image.load()
        vector = provider.embed(image)
        persist_reference_embedding(
            container,
            storage_key,
            image,
            vector=vector,
            source_sha256=digest,
        )
        return vector
    identity = provider_runtime_identity(
        container,
        provider,
        lane="COPY",
        source_sha256=digest,
    )
    key = embedding_key(storage_key, provider.name, identity["identity_digest_sha256"])
    try:
        cached = container.storage.read(key)
    except FileNotFoundError:
        increment_counter("copy_embedding_cache_miss")
    else:
        try:
            vector = decode_embedding(cached, lane="COPY", expected_identity=identity)
        except (TypeError, ValueError):
            increment_counter("copy_embedding_cache_invalidated")
        else:
            increment_counter("copy_embedding_cache_hit")
            return vector
    try:
        raw = container.storage.read(storage_key) if raw is None else raw
        with Image.open(BytesIO(raw)) as opened:
            image = opened.convert("RGB")
            image.load()
        vector = provider.embed(image)
        persist_reference_embedding(
            container,
            storage_key,
            image,
            vector=vector,
            source_sha256=digest,
        )
        increment_counter("copy_embedding_generated")
        return vector
    except Exception:
        increment_counter("copy_embedding_generation_failed")
        raise
