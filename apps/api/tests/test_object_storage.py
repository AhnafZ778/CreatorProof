from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.services import storage as storage_module
from app.services.storage import LocalObjectStore, ObjectStore, S3ObjectStore, build_object_store


class MissingObjectError(Exception):
    response = {
        "Error": {"Code": "NoSuchKey"},
        "ResponseMetadata": {"HTTPStatusCode": 404},
    }


class FakeS3Client:
    def __init__(self) -> None:
        self.objects: dict[str, dict] = {}
        self.put_calls: list[dict] = []
        self.presign_calls: list[dict] = []
        self.head_bucket_calls: list[dict] = []

    def put_object(self, **request):
        self.put_calls.append(request)
        self.objects[request["Key"]] = {
            "raw": bytes(request["Body"]),
            "content_type": request.get("ContentType"),
            "metadata": request.get("Metadata", {}),
        }
        return {"ETag": '"put-etag"'}

    def get_object(self, **request):
        try:
            stored = self.objects[request["Key"]]
        except KeyError as exc:
            raise MissingObjectError from exc
        return {"Body": BytesIO(stored["raw"])}

    def head_object(self, **request):
        try:
            stored = self.objects[request["Key"]]
        except KeyError as exc:
            raise MissingObjectError from exc
        return {
            "ContentLength": len(stored["raw"]),
            "ContentType": stored["content_type"],
            "ETag": '"head-etag"',
            "Metadata": stored["metadata"],
        }

    def delete_object(self, **request):
        self.objects.pop(request["Key"], None)
        return {}

    def list_objects_v2(self, **request):
        keys = sorted(key for key in self.objects if key.startswith(request["Prefix"]))
        return {"Contents": [{"Key": key} for key in keys], "IsTruncated": False}

    def delete_objects(self, **request):
        for item in request["Delete"]["Objects"]:
            self.objects.pop(item["Key"], None)
        return {}

    def copy_object(self, **request):
        source = self.objects[request["CopySource"]["Key"]]
        self.objects[request["Key"]] = {
            "raw": source["raw"],
            "content_type": source["content_type"],
            "metadata": dict(source["metadata"]),
        }
        return {}

    def generate_presigned_url(self, operation, **request):
        call = {"operation": operation, **request}
        self.presign_calls.append(call)
        key = request["Params"]["Key"]
        return f"https://private.invalid/{operation}/{key}?signature=redacted"

    def head_bucket(self, **request):
        self.head_bucket_calls.append(request)
        return {}


def s3_store(client: FakeS3Client | None = None) -> tuple[S3ObjectStore, FakeS3Client]:
    resolved_client = client or FakeS3Client()
    store = S3ObjectStore(
        bucket="private-test-bucket",
        region="auto",
        endpoint_url="https://account.r2.cloudflarestorage.com",
        access_key_id="access-id-must-not-be-logged",
        secret_access_key="secret-must-not-be-logged",
        client=resolved_client,
    )
    return store, resolved_client


def test_local_store_preserves_crud_metadata_and_path_behavior(tmp_path: Path) -> None:
    store = LocalObjectStore(tmp_path / "objects")

    assert isinstance(store, ObjectStore)
    assert store.put("works/tn/work/source.png", b"private-bytes") == ("works/tn/work/source.png")
    assert store.read("works/tn/work/source.png") == b"private-bytes"
    assert store.exists("works/tn/work/source.png") is True
    assert store.head("works/tn/work/source.png") == {
        "key": "works/tn/work/source.png",
        "size_bytes": 13,
        "content_type": "image/png",
        "etag": None,
        "metadata": {},
    }
    with store.materialized_path("works/tn/work/source.png") as path:
        assert path == store.local_path("works/tn/work/source.png")
        assert path.read_bytes() == b"private-bytes"
    assert store.presign_put("x", content_type="image/png") is None
    assert store.presign_get("x") is None

    store.delete("works/tn/work/source.png")
    assert store.head("works/tn/work/source.png") is None


def test_s3_store_matches_crud_and_prefix_contract_without_public_acl() -> None:
    store, client = s3_store()

    assert isinstance(store, ObjectStore)
    assert store.put("scans/tn/scan/candidate.bin", b"candidate") == ("scans/tn/scan/candidate.bin")
    store.put("scans/tn/scan/derived/thumb.bin", b"thumb")
    store.put("scans/tn/scanner/unrelated.bin", b"unrelated")
    assert "ACL" not in client.put_calls[0]
    assert store.read("scans/tn/scan/candidate.bin") == b"candidate"
    assert store.exists("scans/tn/scan/candidate.bin") is True
    assert store.exists("scans/tn/scan/missing.bin") is False
    assert store.head("scans/tn/scan/candidate.bin") == {
        "key": "scans/tn/scan/candidate.bin",
        "size_bytes": 9,
        "content_type": None,
        "etag": "head-etag",
        "metadata": {},
    }
    assert store.list_prefix("scans/tn/scan") == [
        "scans/tn/scan/candidate.bin",
        "scans/tn/scan/derived/thumb.bin",
    ]
    assert store.delete_prefix("scans/tn/scan") == [
        "scans/tn/scan/candidate.bin",
        "scans/tn/scan/derived/thumb.bin",
    ]
    assert store.exists("scans/tn/scanner/unrelated.bin") is True
    assert store.copy("scans/tn/scanner/unrelated.bin", "works/tn/copied.bin") == (
        "works/tn/copied.bin"
    )
    assert store.move("works/tn/copied.bin", "works/tn/moved.bin") == "works/tn/moved.bin"
    assert store.read_bytes("works/tn/moved.bin") == b"unrelated"
    assert store.exists("works/tn/copied.bin") is False
    assert store.status() == {
        "provider": "s3-compatible",
        "region_configured": True,
        "custom_endpoint": True,
        "encrypted_at_rest": None,
        "public_access": False,
        "note": "Objects are private and accessed through authenticated API operations.",
    }


def test_s3_materialization_uses_supplied_bytes_and_removes_temporary_file() -> None:
    store, _ = s3_store()

    with store.materialized_path("scans/tn/scan/candidate.png", raw=b"scan") as path:
        materialized = path
        assert path.read_bytes() == b"scan"
        assert path.suffix == ".png"
    assert materialized.exists() is False


def test_s3_presigned_contract_signs_type_and_size_metadata() -> None:
    store, client = s3_store()

    upload = store.presign_put(
        "uploads/tn/session/source.png",
        content_type="image/png",
        expires_seconds=600,
        max_bytes=4_000_000,
        metadata={
            "creatorproof-purpose": "scan",
            "creatorproof-tenant": "tn_demo",
            "creatorproof-upload-nonce": "nonce-123",
        },
    )
    download = store.presign_get("uploads/tn/session/source.png", expires_seconds=120)

    assert upload == {
        "method": "PUT",
        "url": (
            "https://private.invalid/put_object/uploads/tn/session/source.png?signature=redacted"
        ),
        "headers": {
            "Content-Type": "image/png",
            "x-amz-meta-creatorproof-purpose": "scan",
            "x-amz-meta-creatorproof-tenant": "tn_demo",
            "x-amz-meta-creatorproof-upload-nonce": "nonce-123",
            "x-amz-meta-creatorproof-max-bytes": "4000000",
        },
        "expires_seconds": 600,
        "max_bytes": 4_000_000,
        "max_bytes_enforced": False,
    }
    assert download["method"] == "GET"
    assert download["headers"] == {}
    put_params = client.presign_calls[0]["Params"]
    assert put_params["ContentType"] == "image/png"
    assert put_params["Metadata"] == {
        "creatorproof-purpose": "scan",
        "creatorproof-tenant": "tn_demo",
        "creatorproof-upload-nonce": "nonce-123",
        "creatorproof-max-bytes": "4000000",
    }
    assert "ACL" not in put_params


def test_s3_configuration_is_env_selectable_and_hides_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CREATORPROOF_STORAGE_PROVIDER", "s3")
    monkeypatch.setenv("CREATORPROOF_S3_BUCKET", "private-env-bucket")
    monkeypatch.setenv("CREATORPROOF_S3_REGION", "auto")
    monkeypatch.setenv("CREATORPROOF_S3_ENDPOINT_URL", "https://account.r2.cloudflarestorage.com")
    monkeypatch.setenv("CREATORPROOF_S3_ACCESS_KEY_ID", "env-access-secret")
    monkeypatch.setenv("CREATORPROOF_S3_SECRET_ACCESS_KEY", "env-secret-secret")
    settings = Settings(_env_file=None)

    assert settings.storage_provider == "s3"
    assert "env-access-secret" not in repr(settings)
    assert "env-secret-secret" not in repr(settings)

    captured = {}

    class SelectedS3Store:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(storage_module, "S3ObjectStore", SelectedS3Store)
    selected = build_object_store(settings)
    assert isinstance(selected, SelectedS3Store)
    assert captured["bucket"] == "private-env-bucket"
    assert captured["endpoint_url"] == "https://account.r2.cloudflarestorage.com"


def test_s3_selection_rejects_missing_or_unsafe_configuration() -> None:
    with pytest.raises(ValidationError, match="CREATORPROOF_S3_BUCKET"):
        Settings(environment="test", storage_provider="s3", _env_file=None)
    with pytest.raises(ValidationError, match="must not contain credentials"):
        Settings(
            environment="test",
            storage_provider="s3",
            s3_bucket="bucket",
            s3_region="auto",
            s3_access_key_id="access",
            s3_secret_access_key="secret",
            s3_endpoint_url="https://user:password@example.invalid",
            _env_file=None,
        )


def test_s3_startup_failure_is_clear_and_does_not_repeat_credentials() -> None:
    class FailingClient(FakeS3Client):
        def head_bucket(self, **request):
            del request
            raise RuntimeError("provider rejected request")

    store, _ = s3_store(FailingClient())
    with pytest.raises(RuntimeError, match="verify the configured bucket") as raised:
        store.verify_connection()
    assert "secret-must-not-be-logged" not in str(raised.value)
    assert "access-id-must-not-be-logged" not in str(raised.value)
