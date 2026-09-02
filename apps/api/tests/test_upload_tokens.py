from __future__ import annotations

import pytest

from app.services.storage import LocalObjectStore
from app.services.upload_tokens import (
    UploadGrantError,
    issue_upload_token,
    load_verified_upload,
    verify_upload_token,
)

SECRET = "upload-token-test-secret-that-is-long-enough"


def _issued(**overrides):
    values = {
        "tenant_id": "tn_one",
        "purpose": "scan",
        "key": "incoming/tn_one/scan/upl_one/source.bin",
        "filename": "candidate.png",
        "content_type": "image/png",
        "size_bytes": 4,
        "ttl_seconds": 300,
        "now": 1_000,
        "nonce": "nonce-one",
    }
    values.update(overrides)
    return issue_upload_token(SECRET, **values)


def test_token_is_tenant_purpose_bound_and_expires():
    token, expected = _issued()
    assert (
        verify_upload_token(token, SECRET, tenant_id="tn_one", purpose="scan", now=1_100)
        == expected
    )

    for tenant_id, purpose, now in (
        ("tn_other", "scan", 1_100),
        ("tn_one", "work", 1_100),
        ("tn_one", "scan", 1_300),
    ):
        with pytest.raises(UploadGrantError) as caught:
            verify_upload_token(
                token,
                SECRET,
                tenant_id=tenant_id,
                purpose=purpose,
                now=now,
            )
        assert caught.value.code == "UPLOAD_TOKEN_INVALID"


def test_tampered_token_is_rejected():
    token, _ = _issued()
    payload, signature = token.split(".", 1)
    tampered = f"{payload[:-1]}A.{signature}"
    with pytest.raises(UploadGrantError):
        verify_upload_token(tampered, SECRET, tenant_id="tn_one", purpose="scan", now=1_100)


def test_uploaded_object_must_match_signed_metadata(tmp_path):
    storage = LocalObjectStore(tmp_path)
    _, claims = _issued()
    signed_metadata = {
        "creatorproof-purpose": "scan",
        "creatorproof-tenant": "tn_one",
        "creatorproof-upload-nonce": "nonce-one",
        "creatorproof-size-bytes": "4",
    }
    storage.put_bytes(claims.key, b"data")

    def head_with_signed_metadata(key: str):
        metadata = storage.__class__.head(storage, key)
        assert metadata is not None
        return {**metadata, "content_type": "image/png", "metadata": signed_metadata}

    storage.head = head_with_signed_metadata  # type: ignore[method-assign]
    assert load_verified_upload(storage, claims, max_bytes=10) == b"data"


def test_size_mismatch_is_deleted(tmp_path):
    storage = LocalObjectStore(tmp_path)
    _, claims = _issued()
    storage.put_bytes(
        claims.key,
        b"too-long",
        content_type="image/png",
        metadata={
            "creatorproof-purpose": "scan",
            "creatorproof-tenant": "tn_one",
            "creatorproof-upload-nonce": "nonce-one",
            "creatorproof-size-bytes": "4",
        },
    )
    with pytest.raises(UploadGrantError) as caught:
        load_verified_upload(storage, claims, max_bytes=10)
    assert caught.value.code == "UPLOAD_SIZE_MISMATCH"
    assert not storage.exists(claims.key)


@pytest.mark.parametrize("stored_content_type", [None, "image/jpeg"])
def test_missing_or_mismatched_content_type_is_deleted(tmp_path, stored_content_type):
    storage = LocalObjectStore(tmp_path)
    _, claims = _issued()
    storage.put_bytes(claims.key, b"data")
    signed_metadata = {
        "creatorproof-purpose": "scan",
        "creatorproof-tenant": "tn_one",
        "creatorproof-upload-nonce": "nonce-one",
        "creatorproof-size-bytes": "4",
    }

    def head_with_invalid_type(key: str):
        metadata = storage.__class__.head(storage, key)
        assert metadata is not None
        return {
            **metadata,
            "content_type": stored_content_type,
            "metadata": signed_metadata,
        }

    storage.head = head_with_invalid_type  # type: ignore[method-assign]
    with pytest.raises(UploadGrantError) as caught:
        load_verified_upload(storage, claims, max_bytes=10)
    assert caught.value.code == "UPLOAD_TYPE_MISMATCH"
    assert not storage.exists(claims.key)
