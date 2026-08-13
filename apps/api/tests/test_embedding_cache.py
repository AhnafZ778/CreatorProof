import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from types import SimpleNamespace

import numpy as np
from PIL import Image

from app.services.ai_index import persist_reference_embedding, reference_embedding
from app.services.embedding_cache import provider_runtime_identity
from app.services.storage import LocalObjectStore


class CountingProvider:
    name = "counting-provider"
    available = True
    unavailable_reason = None
    dimensions = 3
    model_identity = "COUNTING_MODEL_V1"
    preprocessing_identity = "RGB_MEAN_V1"
    artifact_sha256 = "a" * 64

    def __init__(self) -> None:
        self.calls = 0

    def status(self) -> dict:
        return {
            "provider": self.name,
            "available": True,
            "artifact_sha256": self.artifact_sha256,
        }

    def embed(self, image: Image.Image) -> np.ndarray:
        self.calls += 1
        vector = np.asarray(image.convert("RGB"), dtype=np.float32).mean(axis=(0, 1)) + 1.0
        return vector / np.linalg.norm(vector)


def _container(tmp_path):
    provider = CountingProvider()
    bundle = SimpleNamespace(
        bundle_id="test-bundle",
        manifest_digest_sha256="b" * 64,
        application_revision="source-v1",
    )
    return SimpleNamespace(
        storage=LocalObjectStore(tmp_path / "objects"),
        ai_retrieval=provider,
        model_bundle=bundle,
    )


def _image_bytes() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (32, 24), (20, 80, 160)).save(buffer, format="PNG")
    return buffer.getvalue()


def test_cache_identity_binds_model_preprocessing_bundle_and_source(tmp_path):
    container = _container(tmp_path)
    provider = container.ai_retrieval
    baseline = provider_runtime_identity(
        container,
        provider,
        lane="COPY",
        source_sha256="c" * 64,
    )

    provider.artifact_sha256 = "d" * 64
    artifact_changed = provider_runtime_identity(
        container,
        provider,
        lane="COPY",
        source_sha256="c" * 64,
    )
    provider.artifact_sha256 = "a" * 64
    provider.preprocessing_identity = "RGB_MEAN_V2"
    preprocessing_changed = provider_runtime_identity(
        container,
        provider,
        lane="COPY",
        source_sha256="c" * 64,
    )
    provider.preprocessing_identity = "RGB_MEAN_V1"
    container.model_bundle.manifest_digest_sha256 = "e" * 64
    bundle_changed = provider_runtime_identity(
        container,
        provider,
        lane="COPY",
        source_sha256="c" * 64,
    )
    source_changed = provider_runtime_identity(
        container,
        provider,
        lane="COPY",
        source_sha256="f" * 64,
    )

    digests = {
        item["identity_digest_sha256"]
        for item in (
            baseline,
            artifact_changed,
            preprocessing_changed,
            bundle_changed,
            source_changed,
        )
    }
    assert len(digests) == 5


def test_legacy_or_tampered_cache_is_never_reused(tmp_path):
    container = _container(tmp_path)
    raw = _image_bytes()
    storage_key = "tenant/catalog/work/source.png"
    container.storage.put(storage_key, raw)
    source_sha256 = hashlib.sha256(raw).hexdigest()
    legacy_key = "tenant/catalog/work/counting-provider.embedding.json"
    container.storage.put(
        legacy_key,
        json.dumps(
            {
                "schema": "creatorproof.visual_embedding.v1",
                "provider": "counting-provider",
                "dimensions": 3,
                "vector": [1.0, 0.0, 0.0],
            }
        ).encode(),
    )

    first = reference_embedding(container, storage_key, source_sha256=source_sha256)
    assert container.ai_retrieval.calls == 1
    assert not np.allclose(first, np.asarray([1.0, 0.0, 0.0], dtype=np.float32))

    key = persist_reference_embedding(
        container,
        storage_key,
        Image.open(BytesIO(raw)),
        vector=first,
        source_sha256=source_sha256,
    )
    payload = json.loads(container.storage.read(key))
    payload["identity"]["preprocessing_identity"] = "TAMPERED"
    container.storage.put(key, json.dumps(payload).encode())

    second = reference_embedding(container, storage_key, source_sha256=source_sha256)
    assert container.ai_retrieval.calls == 2
    assert np.allclose(first, second)


def test_atomic_object_store_writes_never_expose_partial_bytes(tmp_path):
    store = LocalObjectStore(tmp_path / "objects")
    key = "cache/shared.json"
    left = b'{"writer":"left","payload":"' + b"a" * 100_000 + b'"}'
    right = b'{"writer":"right","payload":"' + b"b" * 100_000 + b'"}'

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [
            executor.submit(store.put, key, left if index % 2 == 0 else right)
            for index in range(40)
        ]
        for future in futures:
            future.result()

    final = store.read(key)
    assert final in {left, right}
    assert json.loads(final)["writer"] in {"left", "right"}
