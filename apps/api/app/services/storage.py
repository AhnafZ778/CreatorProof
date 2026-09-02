"""Object storage boundary.

Keys are tenant-prefixed and S3-compatible so the local filesystem backend and a
production bucket share one layout. Deletion works on a prefix, because a
candidate's derived artifacts — thumbnails, normalized copies, alignment
visualizations, embeddings — must disappear with the original upload.
"""

from __future__ import annotations

import logging
import mimetypes
import os
import shutil
import tempfile
from collections.abc import Mapping
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Protocol, TypedDict, runtime_checkable

if TYPE_CHECKING:
    from app.core.config import Settings

logger = logging.getLogger("creatorproof.storage")


class ObjectMetadata(TypedDict):
    key: str
    size_bytes: int
    content_type: str | None
    etag: str | None
    metadata: dict[str, str]


class PresignedRequest(TypedDict, total=False):
    method: Literal["GET", "PUT"]
    url: str
    headers: dict[str, str]
    expires_seconds: int
    max_bytes: int | None
    max_bytes_enforced: bool


@runtime_checkable
class ObjectStore(Protocol):
    """Storage contract shared by local development and durable deployments."""

    name: str

    def put(self, key: str, raw: bytes) -> str: ...

    def put_bytes(
        self,
        key: str,
        raw: bytes,
        *,
        content_type: str | None = None,
        metadata: Mapping[str, str] | None = None,
    ) -> str: ...

    def read(self, key: str) -> bytes: ...

    def read_bytes(self, key: str) -> bytes: ...

    def exists(self, key: str) -> bool: ...

    def head(self, key: str) -> ObjectMetadata | None: ...

    def delete(self, key: str | None) -> None: ...

    def list_prefix(self, prefix: str) -> list[str]: ...

    def delete_prefix(self, prefix: str) -> list[str]: ...

    def copy(self, source_key: str, destination_key: str) -> str: ...

    def move(self, source_key: str, destination_key: str) -> str: ...

    def local_path(self, key: str) -> Path | None: ...

    def materialized_path(
        self, key: str, *, raw: bytes | None = None
    ) -> AbstractContextManager[Path]: ...

    def presign_put(
        self,
        key: str,
        *,
        content_type: str,
        expires_seconds: int = 900,
        max_bytes: int | None = None,
        metadata: Mapping[str, str] | None = None,
    ) -> PresignedRequest | None: ...

    def presign_get(self, key: str, *, expires_seconds: int = 300) -> PresignedRequest | None: ...

    def status(self) -> dict: ...


def _normalized_key(key: str) -> str:
    """Return the portable object key accepted by every backend."""

    safe = Path(key)
    if not key or safe.is_absolute() or ".." in safe.parts:
        raise ValueError("Unsafe storage key")
    normalized = str(safe)
    if normalized in {"", "."}:
        raise ValueError("Unsafe storage key")
    return normalized


def _valid_expiry(expires_seconds: int) -> int:
    # AWS SigV4 presigned URLs support at most seven days. S3-compatible services
    # commonly enforce the same boundary.
    if not 1 <= expires_seconds <= 604_800:
        raise ValueError("Presigned URL expiry must be between 1 and 604800 seconds")
    return expires_seconds


def _valid_content_type(content_type: str) -> str:
    normalized = content_type.strip()
    if not normalized or "\r" in normalized or "\n" in normalized:
        raise ValueError("A safe content type is required")
    return normalized


def _normalized_metadata(metadata: Mapping[str, str]) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for raw_name, raw_value in metadata.items():
        name = str(raw_name).strip().lower()
        value = str(raw_value).strip()
        if (
            not name
            or name.startswith("x-amz-meta-")
            or not name.isascii()
            or any(not (character.isalnum() or character in {"-", "_"}) for character in name)
        ):
            raise ValueError("Object metadata names must be safe unprefixed ASCII tokens")
        if not value or not value.isascii() or "\r" in value or "\n" in value:
            raise ValueError("Object metadata values must be non-empty safe ASCII strings")
        normalized[name] = value
    return normalized


def _is_missing_object_error(exc: Exception) -> bool:
    response = getattr(exc, "response", {})
    if not isinstance(response, dict):
        return False
    error = response.get("Error", {})
    metadata = response.get("ResponseMetadata", {})
    code = str(error.get("Code", "")) if isinstance(error, dict) else ""
    status = metadata.get("HTTPStatusCode") if isinstance(metadata, dict) else None
    return status == 404 or code in {"404", "NoSuchKey", "NotFound"}


def tenant_prefix(tenant_id: str) -> str:
    return f"t/{tenant_id}"


def candidate_prefix(tenant_id: str, scan_id: str) -> str:
    return f"scans/{tenant_id}/{scan_id}"


def work_prefix(tenant_id: str, work_id: str) -> str:
    return f"works/{tenant_id}/{work_id}"


class LocalObjectStore:
    name = "local-filesystem"

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _resolve(self, key: str) -> Path:
        safe = Path(_normalized_key(key))
        target = (self.root / safe).resolve()
        if self.root not in target.parents and target != self.root:
            raise ValueError("Unsafe storage key")
        return target

    def put(self, key: str, raw: bytes) -> str:
        target = self._resolve(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.NamedTemporaryFile(
            mode="wb",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        )
        temporary_path = Path(temporary.name)
        try:
            with temporary:
                temporary.write(raw)
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_path, target)
        finally:
            temporary_path.unlink(missing_ok=True)
        return _normalized_key(key)

    def put_bytes(
        self,
        key: str,
        raw: bytes,
        *,
        content_type: str | None = None,
        metadata: Mapping[str, str] | None = None,
    ) -> str:
        del content_type, metadata
        return self.put(key, raw)

    def read(self, key: str) -> bytes:
        return self._resolve(key).read_bytes()

    def read_bytes(self, key: str) -> bytes:
        return self.read(key)

    def exists(self, key: str) -> bool:
        try:
            return self._resolve(key).exists()
        except ValueError:
            return False

    def head(self, key: str) -> ObjectMetadata | None:
        try:
            target = self._resolve(key)
            stats = target.stat()
        except (FileNotFoundError, ValueError):
            return None
        if not target.is_file():
            return None
        return {
            "key": _normalized_key(key),
            "size_bytes": stats.st_size,
            "content_type": mimetypes.guess_type(target.name)[0],
            "etag": None,
            "metadata": {},
        }

    def delete(self, key: str | None) -> None:
        if not key:
            return
        self._resolve(key).unlink(missing_ok=True)

    def list_prefix(self, prefix: str) -> list[str]:
        base = self._resolve(prefix)
        if not base.exists():
            return []
        if base.is_file():
            return [prefix]
        return [
            str(path.relative_to(self.root)) for path in sorted(base.rglob("*")) if path.is_file()
        ]

    def delete_prefix(self, prefix: str) -> list[str]:
        """Remove every object under ``prefix`` and return what was deleted."""
        deleted = self.list_prefix(prefix)
        base = self._resolve(prefix)
        if base.is_file():
            base.unlink(missing_ok=True)
        elif base.exists():
            shutil.rmtree(base, ignore_errors=True)
        remaining = self.list_prefix(prefix)
        if remaining:
            logger.warning("storage_prefix_partially_deleted prefix=%s", prefix)
        return [key for key in deleted if key not in set(remaining)]

    def copy(self, source_key: str, destination_key: str) -> str:
        return self.put(destination_key, self.read(source_key))

    def move(self, source_key: str, destination_key: str) -> str:
        source = self._resolve(source_key)
        destination = self._resolve(destination_key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.replace(source, destination)
        return _normalized_key(destination_key)

    def local_path(self, key: str) -> Path | None:
        return self._resolve(key)

    @contextmanager
    def materialized_path(self, key: str, *, raw: bytes | None = None):
        # `raw` is accepted so callers can use one backend-neutral code path.
        # The durable local object remains authoritative for this backend.
        del raw
        yield self._resolve(key)

    def presign_put(
        self,
        key: str,
        *,
        content_type: str,
        expires_seconds: int = 900,
        max_bytes: int | None = None,
        metadata: Mapping[str, str] | None = None,
    ) -> None:
        del key, content_type, expires_seconds, max_bytes, metadata
        return None

    def presign_get(self, key: str, *, expires_seconds: int = 300) -> None:
        del key, expires_seconds
        return None

    def status(self) -> dict:
        return {
            "provider": self.name,
            "root": str(self.root),
            "encrypted_at_rest": False,
            "public_access": False,
            "note": (
                "Local filesystem storage is a development backend. Production requires "
                "an S3-compatible bucket with encryption, no public access and lifecycle "
                "rules for short-lived candidate objects."
            ),
        }


class S3ObjectStore:
    """Private S3-compatible storage for AWS S3, Cloudflare R2 and MinIO.

    S3's default object ACL is private. We intentionally do not send an ACL
    header: modern S3 buckets often disable ACLs, while R2 and some MinIO
    deployments do not implement them. The adapter never creates a public URL.
    """

    name = "s3-compatible"

    def __init__(
        self,
        *,
        bucket: str,
        region: str,
        access_key_id: str,
        secret_access_key: str,
        endpoint_url: str | None = None,
        client=None,
    ) -> None:
        self.bucket = bucket
        self.region = region
        self.endpoint_url = endpoint_url or None
        if client is None:
            import boto3
            from botocore.config import Config

            client = boto3.client(
                "s3",
                region_name=region,
                endpoint_url=self.endpoint_url,
                aws_access_key_id=access_key_id,
                aws_secret_access_key=secret_access_key,
                config=Config(
                    signature_version="s3v4",
                    retries={"max_attempts": 3, "mode": "standard"},
                    s3={"addressing_style": "path" if self.endpoint_url else "auto"},
                ),
            )
        self._client = client

    def verify_connection(self) -> None:
        """Fail deployment startup before accepting uploads with unusable storage."""

        try:
            self._client.head_bucket(Bucket=self.bucket)
        except Exception as exc:
            raise RuntimeError(
                "S3 object storage startup check failed; verify the configured bucket, "
                "region, endpoint and credentials"
            ) from exc

    def put(self, key: str, raw: bytes) -> str:
        return self.put_bytes(key, raw)

    def put_bytes(
        self,
        key: str,
        raw: bytes,
        *,
        content_type: str | None = None,
        metadata: Mapping[str, str] | None = None,
    ) -> str:
        normalized = _normalized_key(key)
        request: dict = {"Bucket": self.bucket, "Key": normalized, "Body": raw}
        if content_type is not None:
            request["ContentType"] = _valid_content_type(content_type)
        if metadata:
            request["Metadata"] = _normalized_metadata(metadata)
        self._client.put_object(**request)
        return normalized

    def read(self, key: str) -> bytes:
        normalized = _normalized_key(key)
        try:
            response = self._client.get_object(Bucket=self.bucket, Key=normalized)
        except Exception as exc:
            if _is_missing_object_error(exc):
                raise FileNotFoundError(normalized) from exc
            raise
        body = response["Body"]
        try:
            return bytes(body.read())
        finally:
            close = getattr(body, "close", None)
            if callable(close):
                close()

    def read_bytes(self, key: str) -> bytes:
        return self.read(key)

    def exists(self, key: str) -> bool:
        try:
            normalized = _normalized_key(key)
            self._client.head_object(Bucket=self.bucket, Key=normalized)
        except ValueError:
            return False
        except Exception as exc:
            if _is_missing_object_error(exc):
                return False
            raise
        return True

    def head(self, key: str) -> ObjectMetadata | None:
        normalized = _normalized_key(key)
        try:
            response = self._client.head_object(Bucket=self.bucket, Key=normalized)
        except Exception as exc:
            if _is_missing_object_error(exc):
                return None
            raise
        raw_metadata = response.get("Metadata", {})
        metadata = (
            {str(name): str(value) for name, value in raw_metadata.items()}
            if isinstance(raw_metadata, dict)
            else {}
        )
        etag = response.get("ETag")
        return {
            "key": normalized,
            "size_bytes": int(response.get("ContentLength", 0)),
            "content_type": response.get("ContentType"),
            "etag": str(etag).strip('"') if etag else None,
            "metadata": metadata,
        }

    def delete(self, key: str | None) -> None:
        if not key:
            return
        normalized = _normalized_key(key)
        self._client.delete_object(Bucket=self.bucket, Key=normalized)

    def list_prefix(self, prefix: str) -> list[str]:
        normalized = _normalized_key(prefix).rstrip("/")
        continuation_token: str | None = None
        found: list[str] = []
        while True:
            request: dict = {"Bucket": self.bucket, "Prefix": normalized, "MaxKeys": 1000}
            if continuation_token:
                request["ContinuationToken"] = continuation_token
            response = self._client.list_objects_v2(**request)
            for item in response.get("Contents", []):
                key = str(item.get("Key", ""))
                if key == normalized or key.startswith(f"{normalized}/"):
                    found.append(key)
            if not response.get("IsTruncated"):
                break
            continuation_token = response.get("NextContinuationToken")
            if not continuation_token:
                raise RuntimeError("S3 prefix listing was truncated without a continuation token")
        return sorted(set(found))

    def delete_prefix(self, prefix: str) -> list[str]:
        keys = self.list_prefix(prefix)
        deleted: list[str] = []
        for offset in range(0, len(keys), 1000):
            batch = keys[offset : offset + 1000]
            response = self._client.delete_objects(
                Bucket=self.bucket,
                Delete={"Objects": [{"Key": key} for key in batch], "Quiet": True},
            )
            failed = {
                str(item.get("Key", "")) for item in response.get("Errors", []) if item.get("Key")
            }
            deleted.extend(key for key in batch if key not in failed)
        remaining = self.list_prefix(prefix)
        if remaining:
            logger.warning("storage_prefix_partially_deleted prefix=%s", prefix)
        remaining_set = set(remaining)
        return [key for key in deleted if key not in remaining_set]

    def copy(self, source_key: str, destination_key: str) -> str:
        source = _normalized_key(source_key)
        destination = _normalized_key(destination_key)
        self._client.copy_object(
            Bucket=self.bucket,
            Key=destination,
            CopySource={"Bucket": self.bucket, "Key": source},
            MetadataDirective="COPY",
        )
        return destination

    def move(self, source_key: str, destination_key: str) -> str:
        destination = self.copy(source_key, destination_key)
        self.delete(source_key)
        return destination

    def local_path(self, key: str) -> None:
        _normalized_key(key)
        return None

    @contextmanager
    def materialized_path(self, key: str, *, raw: bytes | None = None):
        normalized = _normalized_key(key)
        payload = self.read(normalized) if raw is None else raw
        suffix = Path(normalized).suffix
        descriptor, temporary_name = tempfile.mkstemp(prefix="creatorproof-object-", suffix=suffix)
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as temporary:
                temporary.write(payload)
                temporary.flush()
                os.fsync(temporary.fileno())
            yield temporary_path
        finally:
            temporary_path.unlink(missing_ok=True)

    def presign_put(
        self,
        key: str,
        *,
        content_type: str,
        expires_seconds: int = 900,
        max_bytes: int | None = None,
        metadata: Mapping[str, str] | None = None,
    ) -> PresignedRequest:
        normalized = _normalized_key(key)
        normalized_content_type = _valid_content_type(content_type)
        expiry = _valid_expiry(expires_seconds)
        if max_bytes is not None and max_bytes <= 0:
            raise ValueError("Presigned upload byte limit must be positive")
        signed_metadata = _normalized_metadata(metadata or {})
        headers = {"Content-Type": normalized_content_type}
        params: dict = {
            "Bucket": self.bucket,
            "Key": normalized,
            "ContentType": normalized_content_type,
        }
        if max_bytes is not None:
            # PUT signatures cannot express a `content-length-range` condition.
            # Sign immutable metadata so the completion endpoint can compare the
            # intended cap with HEAD ContentLength before accepting the object.
            value = str(max_bytes)
            signed_metadata["creatorproof-max-bytes"] = value
        if signed_metadata:
            params["Metadata"] = signed_metadata
            headers.update({f"x-amz-meta-{name}": value for name, value in signed_metadata.items()})
        url = self._client.generate_presigned_url(
            "put_object", Params=params, ExpiresIn=expiry, HttpMethod="PUT"
        )
        return {
            "method": "PUT",
            "url": url,
            "headers": headers,
            "expires_seconds": expiry,
            "max_bytes": max_bytes,
            "max_bytes_enforced": False,
        }

    def presign_get(self, key: str, *, expires_seconds: int = 300) -> PresignedRequest:
        normalized = _normalized_key(key)
        expiry = _valid_expiry(expires_seconds)
        url = self._client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": normalized},
            ExpiresIn=expiry,
            HttpMethod="GET",
        )
        return {
            "method": "GET",
            "url": url,
            "headers": {},
            "expires_seconds": expiry,
        }

    def status(self) -> dict:
        # Bucket names, endpoint URLs and all credentials stay out of the public
        # health response. Endpoint configuration is represented as a boolean only.
        return {
            "provider": self.name,
            "region_configured": bool(self.region),
            "custom_endpoint": bool(self.endpoint_url),
            "encrypted_at_rest": None,
            "public_access": False,
            "note": "Objects are private and accessed through authenticated API operations.",
        }


def build_object_store(settings: Settings) -> ObjectStore:
    if settings.storage_provider == "local":
        return LocalObjectStore(settings.storage_root)
    store = S3ObjectStore(
        bucket=settings.s3_bucket,
        region=settings.s3_region,
        endpoint_url=settings.s3_endpoint_url or None,
        access_key_id=settings.s3_access_key_id,
        secret_access_key=settings.s3_secret_access_key,
    )
    if settings.environment == "production":
        store.verify_connection()
    return store
