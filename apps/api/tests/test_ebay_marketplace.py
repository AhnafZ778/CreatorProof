"""eBay OAuth, safe discovery and real catalog-scan integration (no remote calls)."""

import asyncio
import base64
import json

import httpx
import pytest

from app.core.config import Settings
from app.services.marketplaces import MarketplaceClient, MarketplaceError
from app.services.storage import build_object_store


def listing(**overrides):
    return {
        "itemId": "v1|123456789012|0",
        "title": "Artist print",
        "itemWebUrl": "https://www.sandbox.ebay.com/itm/123456789012",
        "image": {"imageUrl": "https://i.ebayimg.com/images/print.jpg"},
        "thumbnailImages": [{"imageUrl": "https://i.ebayimg.com/images/thumb.jpg"}],
        "seller": {"username": "demo-seller"},
        "itemLocation": {"country": "US", "city": "Seattle"},
        **overrides,
    }


def connector(tmp_path, handler, **overrides):
    settings = Settings(_env_file=None, storage_root=tmp_path / "objects")
    return MarketplaceClient(
        storage=build_object_store(settings),
        transport=httpx.MockTransport(handler),
        **{"ebay_client_id": "client-private", "ebay_client_secret": "secret-private", **overrides},
    )


def token_response():
    return httpx.Response(
        200,
        json={
            "access_token": "token-private",
            "expires_in": 7200,
            "token_type": "Application Access Token",
        },
    )


def test_oauth_search_cache_observation_download_and_secret_isolation(tmp_path):
    requests = []

    def handler(request):
        requests.append(request)
        assert request.url.host in {"api.sandbox.ebay.com", "i.ebayimg.com"}
        if request.method == "POST":
            assert request.url.path == "/identity/v1/oauth2/token"
            assert (
                request.headers["Authorization"]
                == "Basic " + base64.b64encode(b"client-private:secret-private").decode()
            )
            assert b"grant_type=client_credentials" in request.content
            assert b"scope=https%3A%2F%2Fapi.ebay.com%2Foauth%2Fapi_scope" in request.content
            return token_response()
        if request.url.host == "i.ebayimg.com":
            assert "authorization" not in request.headers
            return httpx.Response(
                200, headers={"Content-Type": "image/png"}, content=b"image-bytes"
            )
        assert request.headers["Authorization"] == "Bearer token-private"
        assert request.headers["X-EBAY-C-MARKETPLACE-ID"] == "EBAY_US"
        assert request.url.params["offset"] == "3"
        assert request.url.params["limit"] == "3"
        return httpx.Response(200, json={"itemSummaries": [listing()]})

    async def run():
        source = connector(tmp_path, handler)
        first = await source.search("ebay", query="art", page=2, per_page=3)
        assert await source.search("ebay", query="art", page=2, per_page=3) == first
        assert len(requests) == 2  # OAuth + search; identical query uses the 60s cache.
        second = await source.search("ebay", query="prints", page=2, per_page=3)
        assert len(requests) == 3  # A different query reuses the application token.
        assert second[0].external_id == "sandbox:EBAY_US:v1|123456789012|0"
        assert second[0].metadata["item_location_country"] == "US"
        assert "creator_country" not in second[0].metadata
        observation = source.observe("tenant-a", second[0], search={"query": "prints"})
        assert (
            await source.download(
                source.load_observation("tenant-a", observation["observation_id"])
            )
            == b"image-bytes"
        )
        with pytest.raises(MarketplaceError) as caught:
            source.load_observation("tenant-b", observation["observation_id"])
        assert caught.value.status_code == 404
        serialized = json.dumps(source.provider_statuses()) + "".join(
            path.read_text() for path in (tmp_path / "objects").rglob("*.json")
        )
        for secret in ("client-private", "secret-private", "token-private"):
            assert secret not in serialized

    asyncio.run(run())


@pytest.mark.parametrize(
    "upstream,expected",
    [
        (400, "MARKETPLACE_AUTH_INVALID"),
        (401, "MARKETPLACE_AUTH_INVALID"),
        (429, "MARKETPLACE_RATE_LIMITED"),
        (500, "MARKETPLACE_UPSTREAM_ERROR"),
    ],
)
def test_oauth_errors_are_bounded_and_sanitized(tmp_path, upstream, expected):
    count = 0

    def handler(request):
        nonlocal count
        count += 1
        return httpx.Response(upstream, json={"error_description": "secret-private token-private"})

    async def run():
        with pytest.raises(MarketplaceError) as caught:
            await connector(tmp_path, handler).search("ebay", query="art", per_page=3)
        assert caught.value.code == expected
        assert "private" not in str(caught.value)
        assert count == 1

    asyncio.run(run())


@pytest.mark.parametrize("client_id,secret", [("", ""), ("id", ""), ("", "secret")])
def test_incomplete_credentials_fail_before_network(tmp_path, client_id, secret):
    def handler(request):
        raise AssertionError("No request allowed")

    async def run():
        source = connector(tmp_path, handler, ebay_client_id=client_id, ebay_client_secret=secret)
        assert not source.configured("ebay")
        with pytest.raises(MarketplaceError) as caught:
            await source.search("ebay", query="art", per_page=3)
        assert caught.value.status_code == 503

    asyncio.run(run())


@pytest.mark.parametrize("still_rejected", [False, True])
def test_rejected_token_refreshes_once(tmp_path, still_rejected):
    tokens = searches = 0

    def handler(request):
        nonlocal tokens, searches
        if request.method == "POST":
            tokens += 1
            return token_response()
        searches += 1
        if searches == 1 or still_rejected:
            return httpx.Response(401)
        return httpx.Response(200, json={"itemSummaries": [listing()]})

    async def run():
        source = connector(tmp_path, handler)
        if still_rejected:
            with pytest.raises(MarketplaceError):
                await source.search("ebay", query="art", per_page=3)
        else:
            assert len(await source.search("ebay", query="art", per_page=3)) == 1
        assert tokens == searches == 2

    asyncio.run(run())


def test_expired_token_renews_and_concurrent_searches_share_token(tmp_path):
    tokens = 0

    def handler(request):
        nonlocal tokens
        if request.method == "POST":
            tokens += 1
            return token_response()
        return httpx.Response(200, json={"itemSummaries": [listing()]})

    async def run():
        source = connector(tmp_path, handler)
        await asyncio.gather(
            *(source.search("ebay", query=f"art-{i}", per_page=3) for i in range(4))
        )
        assert tokens == 1
        source._ebay_token_expires_at = 0
        await source.search("ebay", query="new-query", per_page=3)
        assert tokens == 2

    asyncio.run(run())


@pytest.mark.parametrize(
    "row",
    [
        listing(itemId="../../bad"),
        listing(image={"imageUrl": "http://i.ebayimg.com/a.jpg"}),
        listing(image={"imageUrl": "https://localhost/a.jpg"}),
        listing(itemWebUrl="https://www.ebay.com/itm/123"),
    ],
)
def test_unsafe_listing_rejected(tmp_path, row):
    def handler(request):
        return (
            token_response()
            if request.method == "POST"
            else httpx.Response(200, json={"itemSummaries": [row]})
        )

    async def run():
        with pytest.raises(MarketplaceError) as caught:
            await connector(tmp_path, handler).search("ebay", query="art", per_page=3)
        assert caught.value.code == "MARKETPLACE_RESPONSE_INVALID"

    asyncio.run(run())


def test_empty_results_and_listings_without_images(tmp_path):
    def handler(request):
        return (
            token_response()
            if request.method == "POST"
            else httpx.Response(200, json={"itemSummaries": [listing(image={})]})
        )

    async def run():
        assert await connector(tmp_path, handler).search("ebay", query="art", per_page=3) == []

    asyncio.run(run())


def test_real_sandbox_http_image_urls_upgrade_to_https(tmp_path):
    row = listing(
        image={"imageUrl": "http://i.ebayimg.sandbox.ebay.com/images/photo.jpg"},
        thumbnailImages=[{"imageUrl": "http://i.ebayimg.sandbox.ebay.com/images/thumb.jpg"}],
    )
    source = connector(tmp_path, lambda request: httpx.Response(500))
    candidate = source._ebay_candidate(row)
    assert candidate.image_url == "https://i.ebayimg.sandbox.ebay.com/images/photo.jpg"
    assert candidate.thumbnail_url == "https://i.ebayimg.sandbox.ebay.com/images/thumb.jpg"
    for unsafe in (
        "http://i.ebayimg.sandbox.ebay.com.evil.test/photo.jpg",
        "http://private@i.ebayimg.sandbox.ebay.com/photo.jpg",
        "http://i.ebayimg.sandbox.ebay.com:8080/photo.jpg",
    ):
        with pytest.raises(ValueError):
            source._ebay_image_url(unsafe)
    production = connector(
        tmp_path, lambda request: httpx.Response(500), ebay_environment="production"
    )
    with pytest.raises(ValueError):
        production._ebay_image_url(row["image"]["imageUrl"])


def test_production_and_sandbox_never_share_cache_or_asset_identity(tmp_path):
    hosts = []

    def handler(request):
        hosts.append(request.url.host)
        if request.method == "POST":
            return token_response()
        url = (
            "https://www.sandbox.ebay.com/itm/123"
            if request.url.host == "api.sandbox.ebay.com"
            else "https://www.ebay.com/itm/123"
        )
        return httpx.Response(200, json={"itemSummaries": [listing(itemWebUrl=url)]})

    async def run():
        sandbox = connector(tmp_path, handler)
        production = connector(tmp_path, handler, ebay_environment="production")
        [a] = await sandbox.search("ebay", query="art", per_page=3)
        [b] = await production.search("ebay", query="art", per_page=3)
        assert a.external_id != b.external_id
        assert hosts == ["api.sandbox.ebay.com"] * 2 + ["api.ebay.com"] * 2
        assert len(list((tmp_path / "objects" / "source-cache" / "ebay").glob("*.json"))) == 2

    asyncio.run(run())


def test_ebay_pagination_limit_precedes_oauth(tmp_path):
    def handler(request):
        raise AssertionError("No network request allowed")

    async def run():
        with pytest.raises(ValueError, match="10,000"):
            await connector(tmp_path, handler).search("ebay", query="art", page=1000, per_page=30)

    asyncio.run(run())


def test_ebay_api_search_scan_and_admin_history(client, api_key, image_bytes):
    container = client.app.state.container
    raw = image_bytes()

    def handler(request):
        if request.method == "POST":
            return token_response()
        if request.url.host == "i.ebayimg.com":
            return httpx.Response(200, headers={"Content-Type": "image/png"}, content=raw)
        return httpx.Response(200, json={"itemSummaries": [listing()]})

    source = container.marketplaces
    source.ebay_client_id, source.ebay_client_secret = "client-private", "secret-private"
    source.transport = httpx.MockTransport(handler)
    headers = {"X-API-Key": api_key}
    assert client.get("/v1/marketplaces/providers").status_code == 401
    statuses = client.get("/v1/marketplaces/providers", headers=headers)
    assert statuses.status_code == 200
    assert next(row for row in statuses.json() if row["provider"] == "ebay") == {
        "provider": "ebay",
        "configured": True,
        "environment": "sandbox",
        "marketplace_id": "EBAY_US",
    }
    registration = client.post(
        "/v1/works",
        headers=headers,
        data={"catalog_id": "ebay-test", "title": "Artist original"},
        files={"file": ("original.png", raw, "image/png")},
    )
    assert registration.status_code == 201, registration.text
    search = client.post(
        "/v1/marketplaces/search",
        headers=headers,
        json={"provider": "ebay", "query": "art", "per_page": 3},
    )
    assert search.status_code == 200, search.text
    [candidate] = search.json()["results"]
    selected = client.post(
        "/v1/marketplaces/scan",
        headers=headers,
        json={
            "observation_id": candidate["observation_id"],
            "catalog_id": "ebay-test",
            "intended_use": "marketplace monitoring",
            "country_code": "DE",
            "use_context": {"platform": "eBay", "channel": "web"},
        },
    )
    assert selected.status_code == 202, selected.text
    assert selected.json()["scan"]["match_status"] == "MATCH_FOUND"
    assert selected.json()["scan"]["top_match_work_id"] == registration.json()["id"]
    assert selected.json()["scan"]["evidence_packet"]["source_observation"]["provider"] == "ebay"
    context = selected.json()["scan"]["submission_context"]
    assert context["country_code"] == "DE"
    assert context["source_kind"] == "marketplace"
    assert context["source_url"] == candidate["source_url"]
    assert context["source_basis"] == "server_marketplace_observation"
    assert context["use_context"] == {"platform": "eBay", "channel": "web"}
    handoff = client.get(
        f"/v1/admin/user-detections?scan_id={selected.json()['scan']['id']}", headers=headers
    )
    assert handoff.status_code == 200, handoff.text
    [detection] = handoff.json()
    assert detection["source_provider"] == "ebay"
    assert detection["source_url"] == candidate["source_url"]
    assert detection["country_code"] == "DE"
    assert detection["country_basis"] == "submitter_declaration_not_verified_residence"
    payload = {
        "provider": "ebay",
        "query": "art",
        "catalog_id": "ebay-test",
        "per_page": 3,
        "scan_new": True,
    }
    first = client.post("/v1/admin/marketplaces/monitor", headers=headers, json=payload)
    assert first.status_code == 200, first.text
    [asset] = first.json()["new_images"]
    assert asset["classification"] == "COPIED"
    assert asset["scan_id"]
    assert asset["country_code"] is None
    assert asset["metadata"]["item_location_country"] == "US"
    repeat = client.post("/v1/admin/marketplaces/monitor", headers=headers, json=payload)
    assert repeat.status_code == 200, repeat.text
    assert repeat.json()["new_images"] == []
    assert repeat.json()["duplicate_count"] == 1
    assert repeat.json()["history"][0]["id"] == asset["id"]
    assert repeat.json()["history"][0]["scan_id"] == asset["scan_id"]
    for response in [statuses, search, selected, first, repeat]:
        assert "secret-private" not in response.text
        assert "token-private" not in response.text
