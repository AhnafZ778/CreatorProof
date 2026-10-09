"""Saved comparisons preserve bytes, respect tenancy, and keep deletion meaningful."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.core.security import generate_api_key
from app.models import ApiCredential, ReviewCase, Scan, Tenant


def _match(client, api_key, image_bytes, *, automatic=False, retention=3600):
    container = client.app.state.container
    container.settings.candidate_retention_seconds = retention
    container.settings.admin_archive_matches = automatic
    headers = {"X-API-Key": api_key}
    raw = image_bytes()
    registered = client.post(
        "/v1/works",
        headers=headers,
        data={"title": "Saved artwork", "catalog_id": "archive"},
        files={"file": ("art.png", raw, "image/png")},
    )
    assert registered.status_code == 201, registered.text
    scanned = client.post(
        "/v1/scans",
        headers={**headers, "Idempotency-Key": "saved-case-scan"},
        data={"catalog_id": "archive", "intended_use": "commercial publication"},
        files={"file": ("copy.png", raw, "image/png")},
    )
    assert scanned.status_code == 202, scanned.text
    assert scanned.json()["match_status"] == "MATCH_FOUND"
    return scanned.json()["id"], registered.json()["id"], raw, headers


def test_stored_images_survive_candidate_expiry_and_save_is_idempotent(
    client, api_key, image_bytes
):
    scan_id, _, raw, headers = _match(client, api_key, image_bytes)
    path = f"/v1/admin/stored-cases/{scan_id}"
    first = client.post(path, headers=headers)
    assert first.status_code == 200, first.text
    assert client.post(path, headers=headers).json()["stored_case"] == first.json()["stored_case"]
    container = client.app.state.container
    with container.database.session_factory() as db:
        scan = db.get(Scan, scan_id)
        scan.completed_at = datetime.now(UTC) - timedelta(days=2)
        db.commit()
    assert client.get(f"/v1/scans/{scan_id}/media", headers=headers).status_code == 404
    rows = client.get("/v1/admin/stored-cases", headers=headers).json()
    assert len(rows) == 1
    assert rows[0]["candidate_media_expires_at"] is None
    assert "candidate_key" not in rows[0]["stored_case"]
    for kind in ("candidate", "reference"):
        response = client.get(path + f"/media/{kind}", headers=headers)
        assert response.status_code == 200
        assert response.content == raw
        assert response.headers["cache-control"] == "private, no-store"
    assert client.delete(path, headers=headers).status_code == 204
    assert client.get("/v1/admin/stored-cases", headers=headers).json() == []
    assert client.get(path + "/media/candidate", headers=headers).status_code == 404
    assert client.get(f"/v1/scans/{scan_id}", headers=headers).json()["evidence_packet"]


def test_automatic_archive_keeps_registered_matches(client, api_key, image_bytes):
    scan_id, _, _, headers = _match(client, api_key, image_bytes, automatic=True)
    rows = client.get("/v1/admin/stored-cases", headers=headers).json()
    assert len(rows) == 1
    assert rows[0]["scan_id"] == scan_id


def test_zero_retention_is_not_bypassed_by_automatic_archiving(client, api_key, image_bytes):
    scan_id, _, _, headers = _match(client, api_key, image_bytes, automatic=True, retention=0)
    assert client.get("/v1/admin/stored-cases", headers=headers).json() == []
    assert client.post(f"/v1/admin/stored-cases/{scan_id}", headers=headers).status_code == 409


def test_comparison_hash_mismatch_fails_closed(client, api_key, image_bytes):
    scan_id, _, _, headers = _match(client, api_key, image_bytes, automatic=True)
    container = client.app.state.container
    with container.database.session_factory() as db:
        case = db.scalar(select(ReviewCase).where(ReviewCase.scan_id == scan_id))
        container.storage.put_bytes(case.archive_record["candidate_key"], image_bytes(9))
    assert (
        client.get(f"/v1/admin/stored-cases/{scan_id}/media/candidate", headers=headers).status_code
        == 409
    )


def test_work_deletion_removes_archived_comparison_files(client, api_key, image_bytes):
    scan_id, work_id, _, headers = _match(client, api_key, image_bytes, automatic=True)
    container = client.app.state.container
    with container.database.session_factory() as db:
        case = db.scalar(select(ReviewCase).where(ReviewCase.scan_id == scan_id))
        key = case.archive_record["reference_key"]
    response = client.delete(f"/v1/works/{work_id}", headers=headers)
    assert response.status_code == 200, response.text
    assert not container.storage.exists(key)
    assert (
        client.get(f"/v1/admin/stored-cases/{scan_id}/media/reference", headers=headers).status_code
        == 404
    )


def test_stored_comparison_cannot_be_read_or_changed_by_another_tenant(
    client, api_key, image_bytes
):
    scan_id, _, _, headers = _match(client, api_key, image_bytes, automatic=True)
    container = client.app.state.container
    key = generate_api_key(container.settings.api_key_pepper)
    with container.database.session_factory() as db:
        db.add(Tenant(id="tn_archive_other", slug="archive-other", name="Other tenant"))
        db.flush()
        db.add(
            ApiCredential(
                tenant_id="tn_archive_other",
                name="Other operator",
                prefix=key.prefix,
                secret_digest=key.digest,
                role="REVIEWER",
                scopes=["review:read", "review:write"],
            )
        )
        db.commit()
    other = {"X-API-Key": key.secret}
    assert client.get("/v1/admin/stored-cases", headers=other).json() == []
    for method, suffix in (("get", "/media/reference"), ("post", ""), ("delete", "")):
        response = getattr(client, method)(
            f"/v1/admin/stored-cases/{scan_id}{suffix}", headers=other
        )
        assert response.status_code == 404
    assert len(client.get("/v1/admin/stored-cases", headers=headers).json()) == 1
