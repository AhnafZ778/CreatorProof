from __future__ import annotations

import base64
import hashlib
import time
import uuid
from collections.abc import Callable, Sequence
from io import BytesIO
from typing import Literal
from urllib.parse import urlsplit

import httpx
import numpy as np
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field, ValidationError

EMBEDDING_REQUEST_SCHEMA = "creatorproof.embedding-inference.request.v1"
EMBEDDING_RESPONSE_SCHEMA = "creatorproof.embedding-inference.response.v1"
EMBEDDING_NORMALIZATION = "L2_UNIT_V1"
_RETRYABLE_STATUS_CODES = frozenset({408, 429, 500, 502, 503, 504})
_HEX_SHA256_PATTERN = r"^[0-9a-f]{64}$"


class RemoteEmbeddingError(RuntimeError):
    """A safe, non-secret-bearing remote inference failure."""


class RemoteImageV1(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    id: str = Field(min_length=1, max_length=64)
    media_type: Literal["image/png"]
    width: int = Field(ge=1)
    height: int = Field(ge=1)
    sha256: str = Field(pattern=_HEX_SHA256_PATTERN)
    data_base64: str = Field(min_length=1)


class RemoteEmbeddingRequestV1(BaseModel):
    """Strict request contract implemented by an external embedding service."""

    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[EMBEDDING_REQUEST_SCHEMA] = EMBEDDING_REQUEST_SCHEMA
    request_id: str = Field(min_length=1, max_length=64)
    lane: Literal["COPY", "STYLE"]
    model_identity: str = Field(min_length=1, max_length=200)
    preprocessing_identity: str = Field(min_length=1, max_length=200)
    dimensions: int = Field(ge=1, le=65_536)
    required_normalization: Literal[EMBEDDING_NORMALIZATION] = EMBEDDING_NORMALIZATION
    images: list[RemoteImageV1] = Field(min_length=1, max_length=16)


class RemoteVectorV1(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    id: str = Field(min_length=1, max_length=64)
    source_sha256: str = Field(pattern=_HEX_SHA256_PATTERN)
    vector: list[float] = Field(min_length=1, max_length=65_536)


class RemoteEmbeddingResponseV1(BaseModel):
    """Strict response contract; unknown fields and identity drift are rejected."""

    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[EMBEDDING_RESPONSE_SCHEMA]
    request_id: str = Field(min_length=1, max_length=64)
    lane: Literal["COPY", "STYLE"]
    model_identity: str = Field(min_length=1, max_length=200)
    preprocessing_identity: str = Field(min_length=1, max_length=200)
    model_artifact_sha256: str = Field(pattern=_HEX_SHA256_PATTERN)
    dimensions: int = Field(ge=1, le=65_536)
    normalization: Literal[EMBEDDING_NORMALIZATION]
    embeddings: list[RemoteVectorV1] = Field(min_length=1, max_length=16)


class RemoteHTTPEmbeddingProvider:
    """Synchronous, identity-pinned HTTP adapter for learned image embeddings.

    The caller supplies decoded pixels. They are transferred as lossless RGB PNGs so
    offloading does not introduce a second lossy transform. Responses are rejected unless
    model, preprocessing, artifact, dimensions, source digests and L2 normalization all match
    the configured lane. Operational or contract failures never fall back to an unpinned model.
    """

    learned = True

    def __init__(
        self,
        *,
        name: str,
        lane: Literal["COPY", "STYLE"],
        endpoint_url: str,
        auth_token: str,
        model_identity: str,
        preprocessing_identity: str,
        expected_artifact_sha256: str,
        dimensions: int,
        timeout_seconds: float = 30.0,
        max_attempts: int = 2,
        retry_backoff_seconds: float = 0.25,
        batch_size: int = 1,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.name = name
        self.lane = lane
        self.endpoint_url = endpoint_url.strip()
        self._auth_token = auth_token.strip()
        self.model_identity = model_identity
        self.preprocessing_identity = preprocessing_identity
        self.expected_sha256 = expected_artifact_sha256.strip().lower()
        self.dimensions = int(dimensions)
        self.timeout_seconds = float(timeout_seconds)
        self.max_attempts = int(max_attempts)
        self.retry_backoff_seconds = float(retry_backoff_seconds)
        self.batch_size = int(batch_size)
        self._client = client or httpx.Client(
            timeout=httpx.Timeout(self.timeout_seconds),
            follow_redirects=False,
        )
        self._sleep = sleep
        self._last_error: str | None = None
        self._last_request_state = "NEVER_CALLED"
        self._last_artifact_sha256: str | None = None

    @property
    def device(self) -> str:
        return "remote"

    @property
    def artifact_sha256(self) -> str | None:
        # The expected digest is part of the cache identity before the first request.
        return self.expected_sha256 or None

    def _configuration_reason(self) -> str | None:
        if not self.endpoint_url:
            return f"{self.lane}_REMOTE_ENDPOINT_URL_MISSING"
        parsed = urlsplit(self.endpoint_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return f"{self.lane}_REMOTE_ENDPOINT_URL_INVALID"
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            return f"{self.lane}_REMOTE_ENDPOINT_URL_UNSAFE"
        if not self._auth_token:
            return f"{self.lane}_REMOTE_AUTH_TOKEN_MISSING"
        if self.dimensions <= 0:
            return f"{self.lane}_REMOTE_DIMENSIONS_INVALID"
        if self.max_attempts < 1 or self.batch_size < 1 or self.batch_size > 16:
            return f"{self.lane}_REMOTE_RETRY_OR_BATCH_CONFIG_INVALID"
        if len(self.expected_sha256) != 64 or any(
            character not in "0123456789abcdef" for character in self.expected_sha256
        ):
            return f"{self.lane}_REMOTE_EXPECTED_ARTIFACT_SHA256_INVALID"
        return None

    @property
    def available(self) -> bool:
        # Reachability is established per request. A transient failure must not permanently
        # disable future scans, while every failed scan remains visibly failed.
        return self._configuration_reason() is None

    @property
    def unavailable_reason(self) -> str | None:
        return self._configuration_reason()

    def status(self) -> dict:
        return {
            "provider": self.name,
            "available": self.available,
            "learned": True,
            "device": self.device,
            "reason": self.unavailable_reason,
            "transport": "HTTPS_JSON" if self.endpoint_url.startswith("https://") else "HTTP_JSON",
            "endpoint_url": self.endpoint_url or None,
            "request_schema": EMBEDDING_REQUEST_SCHEMA,
            "response_schema": EMBEDDING_RESPONSE_SCHEMA,
            "normalization": EMBEDDING_NORMALIZATION,
            "dimensions": self.dimensions,
            "model_identity": self.model_identity,
            "preprocessing_identity": self.preprocessing_identity,
            "expected_artifact_sha256": self.expected_sha256 or None,
            "actual_artifact_sha256": self._last_artifact_sha256,
            "last_request_state": self._last_request_state,
            "last_error": self._last_error,
            "timeout_seconds": self.timeout_seconds,
            "max_attempts": self.max_attempts,
            "batch_size": self.batch_size,
            "authentication": "BEARER_TOKEN_CONFIGURED" if self._auth_token else "NOT_CONFIGURED",
            "credential_values_exposed": False,
        }

    @staticmethod
    def _encode_image(image: Image.Image, image_id: str) -> RemoteImageV1:
        rgb = image.convert("RGB")
        payload = BytesIO()
        rgb.save(payload, format="PNG", optimize=False, compress_level=6)
        raw = payload.getvalue()
        return RemoteImageV1(
            id=image_id,
            media_type="image/png",
            width=rgb.width,
            height=rgb.height,
            sha256=hashlib.sha256(raw).hexdigest(),
            data_base64=base64.b64encode(raw).decode("ascii"),
        )

    def _post(self, request: RemoteEmbeddingRequestV1) -> httpx.Response:
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self._auth_token}",
            "X-CreatorProof-Embedding-Contract": EMBEDDING_REQUEST_SCHEMA,
        }
        last_code = f"{self.lane}_REMOTE_INFERENCE_FAILED"
        for attempt in range(1, self.max_attempts + 1):
            try:
                response = self._client.post(
                    self.endpoint_url,
                    headers=headers,
                    json=request.model_dump(mode="json"),
                    timeout=self.timeout_seconds,
                )
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_code = f"{self.lane}_REMOTE_{type(exc).__name__.upper()}"
                if attempt == self.max_attempts:
                    raise RemoteEmbeddingError(last_code) from exc
            else:
                if response.status_code == 200:
                    return response
                if response.status_code in _RETRYABLE_STATUS_CODES:
                    last_code = f"{self.lane}_REMOTE_HTTP_{response.status_code}"
                    if attempt == self.max_attempts:
                        raise RemoteEmbeddingError(last_code)
                else:
                    raise RemoteEmbeddingError(f"{self.lane}_REMOTE_HTTP_{response.status_code}")
            if self.retry_backoff_seconds > 0:
                self._sleep(self.retry_backoff_seconds * (2 ** (attempt - 1)))
        raise RemoteEmbeddingError(last_code)

    def _validate_response(
        self,
        response: httpx.Response,
        request: RemoteEmbeddingRequestV1,
    ) -> list[np.ndarray]:
        content_type = response.headers.get("content-type", "").lower()
        if not content_type.startswith("application/json"):
            raise RemoteEmbeddingError(f"{self.lane}_REMOTE_CONTENT_TYPE_INVALID")
        try:
            payload = RemoteEmbeddingResponseV1.model_validate_json(response.content)
        except (ValidationError, ValueError) as exc:
            raise RemoteEmbeddingError(f"{self.lane}_REMOTE_RESPONSE_CONTRACT_INVALID") from exc

        expected_identity = (
            payload.request_id == request.request_id
            and payload.lane == self.lane
            and payload.model_identity == self.model_identity
            and payload.preprocessing_identity == self.preprocessing_identity
            and payload.model_artifact_sha256 == self.expected_sha256
            and payload.dimensions == self.dimensions
        )
        if not expected_identity:
            raise RemoteEmbeddingError(f"{self.lane}_REMOTE_IDENTITY_MISMATCH")

        expected_images = {item.id: item for item in request.images}
        returned = {item.id: item for item in payload.embeddings}
        if len(returned) != len(payload.embeddings) or set(returned) != set(expected_images):
            raise RemoteEmbeddingError(f"{self.lane}_REMOTE_RESULT_IDS_INVALID")

        vectors: list[np.ndarray] = []
        for requested in request.images:
            result = returned[requested.id]
            if result.source_sha256 != requested.sha256:
                raise RemoteEmbeddingError(f"{self.lane}_REMOTE_SOURCE_DIGEST_MISMATCH")
            vector = np.asarray(result.vector, dtype=np.float32)
            if vector.ndim != 1 or vector.shape[0] != self.dimensions:
                raise RemoteEmbeddingError(f"{self.lane}_REMOTE_DIMENSIONS_MISMATCH")
            if not np.isfinite(vector).all():
                raise RemoteEmbeddingError(f"{self.lane}_REMOTE_VECTOR_NONFINITE")
            norm = float(np.linalg.norm(vector))
            if norm <= 1e-12 or abs(norm - 1.0) > 0.005:
                raise RemoteEmbeddingError(f"{self.lane}_REMOTE_VECTOR_NOT_L2_NORMALIZED")
            vectors.append(vector / norm)
        self._last_artifact_sha256 = payload.model_artifact_sha256
        return vectors

    def _embed_chunk(
        self,
        images: Sequence[tuple[str, Image.Image]],
    ) -> list[np.ndarray]:
        request = RemoteEmbeddingRequestV1(
            request_id=uuid.uuid4().hex,
            lane=self.lane,
            model_identity=self.model_identity,
            preprocessing_identity=self.preprocessing_identity,
            dimensions=self.dimensions,
            images=[self._encode_image(image, image_id) for image_id, image in images],
        )
        response = self._post(request)
        return self._validate_response(response, request)

    def embed(self, image: Image.Image) -> np.ndarray:
        return self.embed_many([image])[0]

    def embed_many(self, images: list[Image.Image]) -> list[np.ndarray]:
        if not images:
            return []
        if not self.available:
            raise RemoteEmbeddingError(self.unavailable_reason or "REMOTE_EMBEDDING_UNAVAILABLE")
        indexed = [(f"image-{index:06d}", image) for index, image in enumerate(images)]
        vectors: list[np.ndarray] = []
        try:
            for start in range(0, len(indexed), self.batch_size):
                vectors.extend(self._embed_chunk(indexed[start : start + self.batch_size]))
        except RemoteEmbeddingError as exc:
            self._last_request_state = "FAILED"
            self._last_error = str(exc)
            raise
        self._last_request_state = "SUCCEEDED"
        self._last_error = None
        return vectors

    @staticmethod
    def similarity(left: np.ndarray, right: np.ndarray) -> float:
        if left.shape != right.shape or left.ndim != 1:
            raise ValueError("Embedding shapes do not match")
        if not np.isfinite(left).all() or not np.isfinite(right).all():
            raise ValueError("Embedding contains non-finite values")
        return float(np.clip(np.dot(left, right), -1.0, 1.0))
