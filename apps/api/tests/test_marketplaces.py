import asyncio
import json
from pathlib import Path

import httpx

from app.core.config import Settings
from app.services.marketplaces import MarketplaceClient, MarketplaceError
from app.services.storage import build_object_store


def _client(tmp_path: Path, transport: httpx.AsyncBaseTransport) -> MarketplaceClient:
    settings = Settings(storage_root=tmp_path / "objects")
    return MarketplaceClient(
        storage=build_object_store(settings),
        unsplash_access_key="unsplash-test",
        pixabay_api_key="pixabay-test",
        transport=transport,
    )


def test_pixabay_search_normalizes_and_persists_observation(tmp_path: Path) -> None:
    image = b"\xff\xd8\xff\xe0test"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "pixabay.com":
            return httpx.Response(
                200,
                json={
                    "hits": [
                        {
                            "id": 42,
                            "tags": "blue painting",
                            "pageURL": "https://pixabay.com/images/id-42/",
                            "largeImageURL": "https://cdn.pixabay.com/painting.jpg",
                            "previewURL": "https://cdn.pixabay.com/painting-preview.jpg",
                            "user": "creator",
                            "imageWidth": 800,
                            "imageHeight": 600,
                        }
                    ]
                },
            )
        return httpx.Response(200, headers={"content-type": "image/jpeg"}, content=image)

    async def exercise() -> None:
        client = _client(tmp_path, httpx.MockTransport(handler))
        [candidate] = await client.search("pixabay", query="painting", per_page=3)
        observation = client.observe("tn_test", candidate, search={"query": "painting"})
        assert observation["observation_id"].startswith("obs_")
        loaded = client.load_observation("tn_test", observation["observation_id"])
        assert loaded["external_id"] == "42"
        assert await client.download(observation) == image

    asyncio.run(exercise())


def test_provider_key_is_not_serialized_in_cached_results(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "id": "abc123",
                        "alt_description": "test photo",
                        "urls": {
                            "regular": "https://images.unsplash.com/photo.jpg",
                            "small": "https://images.unsplash.com/photo-small.jpg",
                        },
                        "links": {
                            "html": "https://unsplash.com/photos/abc123",
                            "download_location": "https://api.unsplash.com/photos/abc123/download",
                        },
                        "user": {
                            "name": "creator",
                            "links": {"html": "https://unsplash.com/creator"},
                        },
                    }
                ]
            },
        )

    async def exercise() -> None:
        client = _client(tmp_path, httpx.MockTransport(handler))
        await client.search("unsplash", query="photo", per_page=3)
        cache_files = list((tmp_path / "objects").rglob("*.json"))
        assert cache_files
        assert "unsplash-test" not in json.dumps([path.read_text() for path in cache_files])

    asyncio.run(exercise())


def test_invalid_provider_key_fails_closed(tmp_path: Path) -> None:
    settings = Settings(storage_root=tmp_path / "objects")
    client = MarketplaceClient(storage=build_object_store(settings))

    async def exercise() -> None:
        try:
            await client.search("pixabay", query="painting", per_page=3)
        except MarketplaceError as exc:
            assert exc.code == "MARKETPLACE_NOT_CONFIGURED"
            assert exc.status_code == 503
        else:
            raise AssertionError("missing provider credentials must fail closed")

    asyncio.run(exercise())
