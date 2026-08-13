from __future__ import annotations

import json
from io import BytesIO

import numpy as np
from PIL import Image


def style_embedding_key(storage_key: str, provider_name: str) -> str:
    prefix = storage_key.rsplit("/", 1)[0]
    safe_provider = "".join(
        character if character.isalnum() or character in "-_" else "-"
        for character in provider_name
    )
    return f"{prefix}/{safe_provider}.style-embedding.json"


def persist_style_embedding(container, provider, storage_key: str, vector: np.ndarray) -> None:
    payload = {
        "schema": "creatorproof.style_embedding.v1",
        "provider": provider.name,
        "dimensions": int(vector.shape[0]),
        "vector": [round(float(value), 8) for value in vector],
    }
    container.storage.put(
        style_embedding_key(storage_key, provider.name),
        json.dumps(payload, separators=(",", ":")).encode(),
    )


def reference_style_embedding(container, provider, storage_key: str) -> np.ndarray:
    key = style_embedding_key(storage_key, provider.name)
    try:
        payload = json.loads(container.storage.read(key))
        if payload.get("provider") != provider.name:
            raise ValueError("Style embedding provider mismatch")
        vector = np.asarray(payload.get("vector"), dtype=np.float32)
        if vector.ndim != 1 or not np.isfinite(vector).all():
            raise ValueError("Invalid cached style embedding")
        norm = float(np.linalg.norm(vector))
        if norm <= 1e-12:
            raise ValueError("Invalid cached style embedding norm")
        return vector / norm
    except (FileNotFoundError, json.JSONDecodeError, TypeError, ValueError):
        raw = container.storage.read(storage_key)
        with Image.open(BytesIO(raw)) as opened:
            image = opened.convert("RGB")
            image.load()
        vector = provider.embed(image)
        persist_style_embedding(container, provider, storage_key, vector)
        return vector
