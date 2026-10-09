from __future__ import annotations

from pathlib import Path

from app.services.storage import LocalObjectStore
from app.services.upload_tokens import verify_upload_token


class DirectUploadTestStore(LocalObjectStore):
    def __init__(self, root: Path) -> None:
        super().__init__(root)
        self.object_metadata: dict[str, tuple[str | None, dict[str, str]]] = {}

    def put_bytes(self, key, raw, *, content_type=None, metadata=None):
        self.object_metadata[key] = (content_type, dict(metadata or {}))
        return super().put_bytes(key, raw)

    def head(self, key):
        result = super().head(key)
        if result is None:
            return None
        content_type, metadata = self.object_metadata.get(key, (result["content_type"], {}))
        return {**result, "content_type": content_type, "metadata": metadata}

    def delete(self, key):
        if key:
            self.object_metadata.pop(key, None)
        return super().delete(key)

    def presign_put(
        self,
        key,
        *,
        content_type,
        expires_seconds=900,
        max_bytes=None,
        metadata=None,
    ):
        headers = {"Content-Type": content_type}
        headers.update(
            {f"x-amz-meta-{name}": value for name, value in dict(metadata or {}).items()}
        )
        headers["x-amz-meta-creatorproof-max-bytes"] = str(max_bytes)
        return {
            "method": "PUT",
            "url": f"https://objects.invalid/{key}",
            "headers": headers,
            "expires_seconds": expires_seconds,
            "max_bytes": max_bytes,
            "max_bytes_enforced": False,
        }

    def presign_get(self, key, *, expires_seconds=300):
        return {
            "method": "GET",
            "url": f"https://objects.invalid/{key}?expires={expires_seconds}",
            "headers": {},
            "expires_seconds": expires_seconds,
        }


def _grant_and_store(client, image: bytes, purpose: str):
    container = client.app.state.container
    response = client.post(
        "/v1/uploads",
        headers={"X-API-Key": container.settings.dev_api_key},
        json={
            "purpose": purpose,
            "filename": "image.png",
            "content_type": "image/png",
            "size_bytes": len(image),
        },
    )
    assert response.status_code == 201, response.text
    grant = response.json()
    claims = verify_upload_token(
        grant["upload_token"],
        container.settings.upload_token_secret,
        tenant_id=container.settings.dev_tenant_id,
        purpose=purpose,
    )
    metadata = {
        name.removeprefix("x-amz-meta-"): value
        for name, value in grant["upload"]["headers"].items()
        if name.lower().startswith("x-amz-meta-")
    }
    container.storage.put_bytes(
        claims.key,
        image,
        content_type="image/png",
        metadata=metadata,
    )
    return grant, claims


def test_direct_scan_upload_is_consumed(client, image_bytes, tmp_path):
    store = DirectUploadTestStore(tmp_path / "direct-objects")
    client.app.state.container.storage = store
    grant, claims = _grant_and_store(client, image_bytes(), "scan")

    response = client.post(
        "/v1/scans/from-upload",
        headers={
            "X-API-Key": client.app.state.container.settings.dev_api_key,
            "Idempotency-Key": "direct-scan-one",
        },
        json={
            "upload_token": grant["upload_token"],
            "catalog_id": "demo-catalog",
            "intended_use": "editorial",
            "country_code": "GB",
            "source_url": "https://publisher.example/submitted-image",
        },
    )

    assert response.status_code == 202, response.text
    assert response.json()["catalog_id"] == "demo-catalog"
    assert response.json()["submission_context"]["country_code"] == "GB"
    assert response.json()["submission_context"]["source_url"] == (
        "https://publisher.example/submitted-image"
    )
    assert store.exists(claims.key) is False
    replay = client.post(
        "/v1/scans/from-upload",
        headers={"X-API-Key": client.app.state.container.settings.dev_api_key},
        json={
            "upload_token": grant["upload_token"],
            "catalog_id": "demo-catalog",
            "intended_use": "editorial",
            "country_code": "GB",
            "source_url": "https://publisher.example/submitted-image",
        },
    )
    assert replay.status_code == 202
    assert replay.json()["id"] == response.json()["id"]
    changed_source = client.post(
        "/v1/scans/from-upload",
        headers={"X-API-Key": client.app.state.container.settings.dev_api_key},
        json={
            "upload_token": grant["upload_token"],
            "catalog_id": "demo-catalog",
            "intended_use": "editorial",
            "country_code": "GB",
            "source_url": "https://publisher.example/different-image",
        },
    )
    assert changed_source.status_code == 409


def test_direct_work_upload_and_media_redirect(client, image_bytes, tmp_path):
    store = DirectUploadTestStore(tmp_path / "direct-objects")
    client.app.state.container.storage = store
    grant, claims = _grant_and_store(client, image_bytes(2), "work")

    response = client.post(
        "/v1/works/from-upload",
        headers={"X-API-Key": client.app.state.container.settings.dev_api_key},
        json={
            "upload_token": grant["upload_token"],
            "catalog_id": "artist-one",
            "title": "Direct work",
            "rights_path": "NO_LICENSE_INFO",
            "allowed_uses": "[]",
            "claim_state": "ASSERTED",
        },
    )

    assert response.status_code == 201, response.text
    assert store.exists(claims.key) is False
    replay = client.post(
        "/v1/works/from-upload",
        headers={"X-API-Key": client.app.state.container.settings.dev_api_key},
        json={
            "upload_token": grant["upload_token"],
            "catalog_id": "artist-one",
            "title": "Direct work",
            "rights_path": "NO_LICENSE_INFO",
            "allowed_uses": "[]",
            "claim_state": "ASSERTED",
        },
    )
    assert replay.status_code == 201
    assert replay.json()["id"] == response.json()["id"]
    media = client.get(
        f"/v1/works/{response.json()['id']}/media",
        headers={"X-API-Key": client.app.state.container.settings.dev_api_key},
        follow_redirects=False,
    )
    assert media.status_code == 307
    assert media.headers["location"].startswith("https://objects.invalid/")


def test_direct_upload_rejects_oversize_grant(client):
    container = client.app.state.container
    response = client.post(
        "/v1/uploads",
        headers={"X-API-Key": container.settings.dev_api_key},
        json={
            "purpose": "scan",
            "filename": "huge.png",
            "content_type": "image/png",
            "size_bytes": container.settings.max_upload_bytes + 1,
        },
    )
    assert response.status_code == 413


def test_local_storage_reports_direct_upload_unavailable(client, image_bytes):
    container = client.app.state.container
    response = client.post(
        "/v1/uploads",
        headers={"X-API-Key": container.settings.dev_api_key},
        json={
            "purpose": "scan",
            "filename": "candidate.png",
            "content_type": "image/png",
            "size_bytes": len(image_bytes()),
        },
    )
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "DIRECT_UPLOAD_UNAVAILABLE"


def test_tampered_completion_token_is_rejected(client, image_bytes, tmp_path):
    store = DirectUploadTestStore(tmp_path / "direct-objects")
    client.app.state.container.storage = store
    grant, _ = _grant_and_store(client, image_bytes(), "scan")
    token = grant["upload_token"]
    replacement = "A" if token[0] != "A" else "B"

    response = client.post(
        "/v1/scans/from-upload",
        headers={
            "X-API-Key": client.app.state.container.settings.dev_api_key,
            "Idempotency-Key": "direct-tamper-one",
        },
        json={
            "upload_token": replacement + token[1:],
            "catalog_id": "demo-catalog",
            "intended_use": "editorial",
        },
    )
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "UPLOAD_TOKEN_INVALID"
