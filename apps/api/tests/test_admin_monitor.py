from __future__ import annotations

from io import BytesIO

from PIL import Image

from app.services.marketplaces import MarketplaceCandidate


def test_admin_monitor_retains_history_and_deduplicates(client, monkeypatch) -> None:
    container = client.app.state.container
    candidate = MarketplaceCandidate(
        provider="pixabay",
        external_id="asset-1",
        title="A monitored image",
        source_url="https://pixabay.com/images/asset-1/",
        image_url="https://cdn.pixabay.com/asset-1.jpg",
        thumbnail_url="https://cdn.pixabay.com/asset-1-preview.jpg",
        creator="creator",
        width=100,
        height=100,
        metadata={"provider_license": "https://pixabay.com/service/license-summary/"},
    )

    async def search(*_args, **_kwargs):
        return [candidate]

    async def download(*_args, **_kwargs):
        output = BytesIO()
        Image.new("RGB", (64, 64), (20, 80, 200)).save(output, format="PNG")
        return output.getvalue()

    monkeypatch.setattr(container.marketplaces, "search", search)
    monkeypatch.setattr(container.marketplaces, "download", download)
    headers = {"X-API-Key": "test-api-key-123"}
    payload = {
        "provider": "pixabay",
        "query": "painting",
        "catalog_id": "default",
        "scan_new": False,
    }

    first = client.post("/v1/admin/marketplaces/monitor", headers=headers, json=payload)
    assert first.status_code == 200
    assert len(first.json()["new_images"]) == 1
    assert first.json()["duplicate_count"] == 0

    second = client.post("/v1/admin/marketplaces/monitor", headers=headers, json=payload)
    assert second.status_code == 200
    assert second.json()["new_images"] == []
    assert second.json()["duplicate_count"] == 1
    assert len(second.json()["history"]) == 1

    asset_id = second.json()["history"][0]["id"]
    draft = client.post(
        "/v1/admin/takedowns/drafts",
        headers=headers,
        json={
            "marketplace_asset_id": asset_id,
            "jurisdiction": "US",
            "claimant_name": "Owner",
            "claimant_email": "owner@example.com",
            "protected_title": "Protected artwork",
            "protected_url": "https://example.com/work",
            "evidence_summary": "The source observation is retained for review.",
        },
    )
    # An unscanned discovery is useful review context, not copyright evidence.
    assert draft.status_code == 409
    assert draft.json()["detail"]["code"] == "COPYRIGHT_NOTICE_NOT_SUPPORTED"


def test_saved_source_history_can_page_beyond_first_200(client, api_key):
    from datetime import UTC, datetime, timedelta

    from app.models import MarketplaceAsset

    container = client.app.state.container
    start = datetime.now(UTC)
    with container.database.session_factory() as db:
        for index in range(205):
            db.add(
                MarketplaceAsset(
                    tenant_id=container.settings.dev_tenant_id,
                    provider="pixabay",
                    external_id=f"archive-{index}",
                    title=f"Saved image {index}",
                    source_url=f"https://pixabay.com/images/archive-{index}/",
                    image_url=f"https://cdn.pixabay.com/archive-{index}.jpg",
                    first_seen_at=start + timedelta(seconds=index),
                    last_seen_at=start + timedelta(seconds=index),
                )
            )
        db.commit()
    headers = {"X-API-Key": api_key}
    first = client.get("/v1/admin/marketplaces/monitor?limit=200", headers=headers)
    older = client.get("/v1/admin/marketplaces/monitor?limit=200&offset=200", headers=headers)
    assert first.status_code == older.status_code == 200
    assert len(first.json()) == 200
    assert len(older.json()) == 5
    assert not {row["id"] for row in first.json()} & {row["id"] for row in older.json()}
    assert older.json()[-1]["external_id"] == "archive-0"
    assert client.get("/v1/admin/marketplaces/monitor?offset=205", headers=headers).json() == []
    assert (
        client.get("/v1/admin/marketplaces/monitor?offset=-1", headers=headers).status_code == 422
    )
