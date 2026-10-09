"""Provider discovery, private observations and bounded image downloads.

Stock-image search nominates candidates; the catalog scan verifies visual reuse.
No provider response establishes misuse or the legal status of a photo.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
import time
from dataclasses import asdict, dataclass
from typing import Literal
from urllib.parse import urlsplit

import anyio
import httpx

from app.models import new_id
from app.services.storage import ObjectStore

MarketplaceName = Literal["unsplash", "pixabay", "ebay"]
_ID = re.compile(r"^[A-Za-z0-9_-]{1,100}$")
_EBAY_ID = re.compile(r"^v1\|[0-9]{1,20}\|[0-9]{1,20}$")
_IMAGE_HOSTS = {
    "unsplash": {"images.unsplash.com", "plus.unsplash.com"},
    "pixabay": {"cdn.pixabay.com", "pixabay.com"},
    "ebay": {"i.ebayimg.com", "i.sandbox.ebayimg.com", "i.ebayimg.sandbox.ebay.com"},
}
_PAGE_HOSTS = {
    "unsplash": {"unsplash.com", "www.unsplash.com"},
    "pixabay": {"pixabay.com", "www.pixabay.com"},
}


class MarketplaceError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 502,
        *,
        upstream_status: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.upstream_status = upstream_status


class _RedactProviderKey(logging.Filter):
    """HTTPX logs request URLs, including Pixabay's required query credential."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        if "pixabay.com" in message:
            record.msg = re.sub(r"([?&]key=)[^&\s\"']+", r"\1[redacted]", message)
            record.args = ()
        return True


logging.getLogger("httpx").addFilter(_RedactProviderKey())


@dataclass(frozen=True, slots=True)
class MarketplaceCandidate:
    provider: MarketplaceName
    external_id: str
    title: str
    source_url: str
    image_url: str
    thumbnail_url: str | None
    creator: str | None
    width: int | None
    height: int | None
    metadata: dict

    def public_record(self) -> dict:
        return asdict(self)


def _safe_url(value: object, hosts: set[str]) -> str:
    if not isinstance(value, str):
        raise ValueError("Missing provider URL")
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in hosts
        or parsed.port not in {None, 443}
        or parsed.username
        or parsed.password
        or parsed.fragment
    ):
        raise ValueError("Unsafe provider URL")
    return value


def _text(value: object, fallback: str = "") -> str:
    return str(value or fallback).strip()[:240]


def _dimension(value: object) -> int | None:
    return value if isinstance(value, int) and value > 0 else None


class MarketplaceClient:
    def __init__(
        self,
        *,
        storage: ObjectStore,
        unsplash_access_key: str = "",
        pixabay_api_key: str = "",
        ebay_client_id: str = "",
        ebay_client_secret: str = "",
        ebay_environment: Literal["sandbox", "production"] = "sandbox",
        ebay_marketplace_id: str = "EBAY_US",
        timeout_seconds: float = 20.0,
        max_download_bytes: int = 12 * 1024 * 1024,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.storage = storage
        self.unsplash_access_key = unsplash_access_key.strip()
        self.pixabay_api_key = pixabay_api_key.strip()
        if ebay_environment not in {"sandbox", "production"}:
            raise ValueError("Invalid eBay environment")
        if not re.fullmatch(r"EBAY_[A-Z_]{2,12}", ebay_marketplace_id):
            raise ValueError("Invalid eBay marketplace ID")
        self.ebay_client_id = ebay_client_id.strip()
        self.ebay_client_secret = ebay_client_secret.strip()
        self.ebay_environment = ebay_environment
        self.ebay_marketplace_id = ebay_marketplace_id
        self._ebay_access_token = ""
        self._ebay_token_expires_at = 0.0
        self._ebay_token_lock = anyio.Lock()
        self.timeout_seconds = timeout_seconds
        self.max_download_bytes = max_download_bytes
        self.transport = transport

    def configured(self, provider: MarketplaceName) -> bool:
        if provider == "ebay":
            return bool(self.ebay_client_id and self.ebay_client_secret)
        return bool(self._key(provider))

    def provider_statuses(self) -> list[dict]:
        """Configuration presence only; this endpoint makes no provider calls."""
        return [
            {
                "provider": provider,
                "configured": self.configured(provider),
                "environment": self.ebay_environment if provider == "ebay" else "production",
                "marketplace_id": self.ebay_marketplace_id if provider == "ebay" else None,
            }
            for provider in ("pixabay", "unsplash", "ebay")
        ]

    @property
    def _ebay_api_origin(self) -> str:
        return (
            "https://api.sandbox.ebay.com"
            if self.ebay_environment == "sandbox"
            else "https://api.ebay.com"
        )

    def _key(self, provider: MarketplaceName) -> str:
        if provider not in _IMAGE_HOSTS:
            raise ValueError("Unsupported image source")
        if provider == "ebay":
            # Used only to fingerprint the private search-cache namespace.
            return json.dumps(
                [
                    self.ebay_environment,
                    self.ebay_marketplace_id,
                    self.ebay_client_id,
                    self.ebay_client_secret,
                ]
            )
        return self.unsplash_access_key if provider == "unsplash" else self.pixabay_api_key

    def _require_key(self, provider: MarketplaceName) -> None:
        if not self.configured(provider):
            raise MarketplaceError(
                "MARKETPLACE_NOT_CONFIGURED",
                f"{provider.title()} is not configured on the API server.",
                503,
            )

    async def _request(
        self,
        url: str,
        *,
        params: dict | None = None,
        headers: dict | None = None,
        limit: int,
        image: bool = False,
        method: str = "GET",
        data: dict | None = None,
        oauth: bool = False,
    ) -> bytes:
        try:
            with anyio.fail_after(self.timeout_seconds):
                async with (
                    httpx.AsyncClient(
                        timeout=self.timeout_seconds,
                        follow_redirects=False,
                        headers={"User-Agent": "CreatorProof/0.10"},
                        transport=self.transport,
                    ) as client,
                    client.stream(
                        method, url, params=params, headers=headers, data=data
                    ) as response,
                ):
                    if response.status_code in {401, 403} or (
                        oauth and response.status_code == 400
                    ):
                        raise MarketplaceError(
                            "MARKETPLACE_AUTH_INVALID",
                            "eBay rejected the credentials. Check the Client ID, "
                            "Client Secret and environment."
                            if oauth
                            else "The provider rejected the API key or permissions.",
                            upstream_status=response.status_code,
                        )
                    if response.status_code == 429:
                        raise MarketplaceError(
                            "MARKETPLACE_RATE_LIMITED",
                            "Provider quota reached. Try again later.",
                            429,
                        )
                    if response.status_code != 200:
                        raise MarketplaceError(
                            "MARKETPLACE_UPSTREAM_ERROR",
                            "The image provider could not serve this request.",
                        )
                    if image and not response.headers.get("content-type", "").lower().startswith(
                        "image/"
                    ):
                        raise MarketplaceError(
                            "MARKETPLACE_IMAGE_INVALID",
                            "Provider returned a non-image response.",
                            422,
                        )
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(raw) + len(chunk) > limit:
                            raise MarketplaceError(
                                "MARKETPLACE_RESPONSE_TOO_LARGE",
                                "Provider response exceeds the size limit.",
                                413,
                            )
                        raw.extend(chunk)
                    if not raw:
                        raise MarketplaceError(
                            "MARKETPLACE_RESPONSE_INVALID", "Provider response was empty."
                        )
                    return bytes(raw)
        except (httpx.HTTPError, TimeoutError):
            # HTTPX exceptions can contain Pixabay's query credential.
            raise MarketplaceError(
                "MARKETPLACE_UNREACHABLE",
                "The image provider timed out or could not be reached.",
                504,
            ) from None

    async def _ebay_token(self, *, rejected_token: str | None = None) -> str:
        # Tokens stay in memory and are shared by concurrent requests in this process.
        async with self._ebay_token_lock:
            if rejected_token and rejected_token == self._ebay_access_token:
                self._ebay_token_expires_at = 0
            if self._ebay_access_token and time.monotonic() < self._ebay_token_expires_at:
                return self._ebay_access_token
            basic = base64.b64encode(
                f"{self.ebay_client_id}:{self.ebay_client_secret}".encode()
            ).decode()
            raw = await self._request(
                f"{self._ebay_api_origin}/identity/v1/oauth2/token",
                method="POST",
                oauth=True,
                headers={"Authorization": f"Basic {basic}"},
                data={
                    "grant_type": "client_credentials",
                    "scope": "https://api.ebay.com/oauth/api_scope",
                },
                limit=64 * 1024,
            )
            try:
                body = json.loads(raw)
                token, expires = body["access_token"], body["expires_in"]
                if (
                    not isinstance(token, str)
                    or not token
                    or len(token) > 32_000
                    or body.get("token_type", "Bearer").lower()
                    not in {"bearer", "application access token"}
                    or isinstance(expires, bool)
                    or not isinstance(expires, (int, float))
                    or not 0 < expires <= 86400
                ):
                    raise ValueError("Invalid OAuth token")
            except (ValueError, KeyError, TypeError, AttributeError):
                raise MarketplaceError(
                    "MARKETPLACE_RESPONSE_INVALID", "eBay returned an invalid OAuth response."
                ) from None
            self._ebay_access_token = token
            self._ebay_token_expires_at = time.monotonic() + expires - min(60, expires / 10)
            return token

    async def _ebay_search(self, query: str, page: int, per_page: int) -> bytes:
        offset = (page - 1) * per_page
        if offset + per_page > 10_000:
            raise ValueError(
                "eBay search supports only the first 10,000 results. Use a more specific query."
            )
        token = await self._ebay_token()
        for attempt in range(2):
            try:
                return await self._request(
                    f"{self._ebay_api_origin}/buy/browse/v1/item_summary/search",
                    params={"q": query, "limit": per_page, "offset": offset},
                    headers={
                        "Authorization": f"Bearer {token}",
                        "X-EBAY-C-MARKETPLACE-ID": self.ebay_marketplace_id,
                    },
                    limit=2 * 1024 * 1024,
                )
            except MarketplaceError as exc:
                if attempt == 0 and exc.upstream_status == 401:
                    token = await self._ebay_token(rejected_token=token)
                else:
                    raise
        raise AssertionError("Unreachable")

    async def search(
        self, provider: MarketplaceName, *, query: str, page: int = 1, per_page: int = 10
    ) -> list[MarketplaceCandidate]:
        self._require_key(provider)
        query = query.strip()
        if not query or len(query) > 100 or not 1 <= page <= 1000 or not 3 <= per_page <= 30:
            raise ValueError("Use a query of 1–100 characters, page 1–1000, and 3–30 results.")
        # Pixabay requires 24-hour caching. Unsplash uses a short cache to save quota.
        digest = hashlib.sha256(
            json.dumps(
                [
                    provider,
                    query,
                    page,
                    per_page,
                    hashlib.sha256(self._key(provider).encode()).hexdigest(),
                ]
            ).encode()
        ).hexdigest()
        cache_key = f"source-cache/{provider}/{digest}.json"
        try:
            cached = json.loads(self.storage.read(cache_key))
            if cached["expires_at"] > time.time():
                return [MarketplaceCandidate(**record) for record in cached["results"]]
        except (FileNotFoundError, ValueError, KeyError, TypeError):
            pass
        if provider == "unsplash":
            url = "https://api.unsplash.com/search/photos"
            headers = {
                "Authorization": f"Client-ID {self.unsplash_access_key}",
                "Accept-Version": "v1",
            }
            params = {"query": query, "page": page, "per_page": per_page, "content_filter": "high"}
        elif provider == "pixabay":
            url = "https://pixabay.com/api/"
            headers = {}
            params = {
                "key": self.pixabay_api_key,
                "q": query,
                "page": page,
                "per_page": per_page,
                "image_type": "all",
                "safesearch": "true",
            }
        if provider == "ebay":
            raw = await self._ebay_search(query, page, per_page)
        else:
            raw = await self._request(url, params=params, headers=headers, limit=2 * 1024 * 1024)
        try:
            payload = json.loads(raw)
            rows = (
                payload.get("itemSummaries", [])
                if provider == "ebay"
                else payload["results" if provider == "unsplash" else "hits"]
            )
            if not isinstance(rows, list):
                raise ValueError("Invalid result collection")
            results = [
                self._ebay_candidate(row) if provider == "ebay" else self._candidate(provider, row)
                for row in rows[:per_page]
                if provider != "ebay" or row.get("image", {}).get("imageUrl")
            ]
        except (ValueError, KeyError, TypeError, AttributeError):
            raise MarketplaceError(
                "MARKETPLACE_RESPONSE_INVALID", "Provider returned malformed image data."
            ) from None
        self.storage.put(
            cache_key,
            json.dumps(
                {
                    "expires_at": time.time()
                    + {"pixabay": 86400, "unsplash": 300, "ebay": 60}[provider],
                    "results": [row.public_record() for row in results],
                }
            ).encode(),
        )
        return results

    def _ebay_candidate(self, row: dict) -> MarketplaceCandidate:
        item_id = str(row["itemId"])
        if not _EBAY_ID.fullmatch(item_id):
            raise ValueError("Invalid eBay item ID")
        if self.ebay_environment == "sandbox":
            page_hosts = {"sandbox.ebay.com", "www.sandbox.ebay.com"}
        else:
            page_hosts = {
                f"{prefix}{domain}"
                for prefix in ("", "www.")
                for domain in (
                    "ebay.com",
                    "ebay.co.uk",
                    "ebay.de",
                    "ebay.fr",
                    "ebay.it",
                    "ebay.es",
                    "ebay.com.au",
                    "ebay.ca",
                    "ebay.at",
                    "ebay.be",
                    "ebay.ch",
                    "ebay.ie",
                    "ebay.nl",
                    "ebay.pl",
                    "ebay.com.sg",
                    "ebay.com.hk",
                    "ebay.com.my",
                    "ebay.ph",
                )
            }
        image_url = self._ebay_image_url(row["image"]["imageUrl"])
        thumbnails = row.get("thumbnailImages") or []
        seller = _text((row.get("seller") or {}).get("username")) or None
        location = row.get("itemLocation") or {}
        return MarketplaceCandidate(
            provider="ebay",
            external_id=f"{self.ebay_environment}:{self.ebay_marketplace_id}:{item_id}",
            title=_text(row.get("title"), "eBay listing"),
            source_url=_safe_url(row["itemWebUrl"], page_hosts),
            image_url=image_url,
            thumbnail_url=self._ebay_image_url(thumbnails[0]["imageUrl"])
            if thumbnails
            else image_url,
            creator=seller,
            width=None,
            height=None,
            metadata={
                "item_id": item_id,
                "environment": self.ebay_environment,
                "marketplace_id": self.ebay_marketplace_id,
                "seller_username": seller,
                # Item location is not evidence of the seller's residence or jurisdiction.
                "item_location_country": _text(location.get("country")) or None,
                "item_location_city": _text(location.get("city")) or None,
                "condition": _text(row.get("condition")) or None,
            },
        )

    def _ebay_image_url(self, value: object) -> str:
        # Sandbox Browse responses include old HTTP URLs. Upgrade only exact
        # sandbox CDN hosts, then apply the ordinary HTTPS validation.
        if isinstance(value, str) and self.ebay_environment == "sandbox":
            parsed = urlsplit(value)
            if (
                parsed.scheme == "http"
                and parsed.port is None
                and parsed.hostname in {"i.ebayimg.sandbox.ebay.com", "i.sandbox.ebayimg.com"}
            ):
                value = parsed._replace(scheme="https").geturl()
        return _safe_url(value, _IMAGE_HOSTS["ebay"])

    @staticmethod
    def _candidate(provider: MarketplaceName, row: dict) -> MarketplaceCandidate:
        external_id = str(row["id"])
        if not _ID.fullmatch(external_id):
            raise ValueError("Invalid provider image ID")
        if provider == "unsplash":
            urls, links, user = row["urls"], row["links"], row["user"]
            return MarketplaceCandidate(
                provider=provider,
                external_id=external_id,
                title=_text(row.get("alt_description") or row.get("description"), "Unsplash image"),
                source_url=_safe_url(links["html"], _PAGE_HOSTS[provider]),
                image_url=_safe_url(urls["regular"], _IMAGE_HOSTS[provider]),
                thumbnail_url=_safe_url(urls.get("small") or urls["thumb"], _IMAGE_HOSTS[provider]),
                creator=_text(user.get("name")) or None,
                width=_dimension(row.get("width")),
                height=_dimension(row.get("height")),
                metadata={
                    "provider_license": "https://unsplash.com/license",
                    "creator_url": _safe_url(user["links"]["html"], _PAGE_HOSTS[provider]),
                    "download_location": _safe_url(
                        links["download_location"], {"api.unsplash.com"}
                    ),
                    "created_at": row.get("created_at"),
                    "creator_location": _text(user.get("location")) or None,
                    "creator_country": _text(user.get("country")) or None,
                },
            )
        return MarketplaceCandidate(
            provider=provider,
            external_id=external_id,
            title=_text(row.get("tags"), "Pixabay image"),
            source_url=_safe_url(row["pageURL"], _PAGE_HOSTS[provider]),
            image_url=_safe_url(
                row.get("largeImageURL") or row["webformatURL"], _IMAGE_HOSTS[provider]
            ),
            thumbnail_url=_safe_url(row["previewURL"], _IMAGE_HOSTS[provider]),
            creator=_text(row.get("user")) or None,
            width=_dimension(row.get("imageWidth")),
            height=_dimension(row.get("imageHeight")),
            metadata={
                "provider_license": "https://pixabay.com/service/license-summary/",
                "tags": _text(row.get("tags")),
                "type": _text(row.get("type")),
            },
        )

    def observe(self, tenant_id: str, candidate: MarketplaceCandidate, *, search: dict) -> dict:
        record = {
            **candidate.public_record(),
            "observation_id": new_id("obs"),
            "observed_at": time.time(),
            "expires_at": time.time() + 86400,
            "search": search,
        }
        self.storage.put(
            f"source-observations/{tenant_id}/{record['observation_id']}.json",
            json.dumps(record).encode(),
        )
        return record

    def load_observation(self, tenant_id: str, observation_id: str) -> dict:
        if not re.fullmatch(r"obs_[a-f0-9]{32}", observation_id):
            raise MarketplaceError(
                "SOURCE_OBSERVATION_NOT_FOUND", "Search again to select an image.", 404
            )
        try:
            record = json.loads(
                self.storage.read(f"source-observations/{tenant_id}/{observation_id}.json")
            )
        except (FileNotFoundError, ValueError):
            raise MarketplaceError(
                "SOURCE_OBSERVATION_NOT_FOUND", "Search again to select an image.", 404
            ) from None
        if record["expires_at"] < time.time():
            raise MarketplaceError(
                "SOURCE_OBSERVATION_EXPIRED", "Search again; this selection expired.", 410
            )
        return record

    async def download(self, observation: dict) -> bytes:
        provider = observation["provider"]
        self._require_key(provider)
        url = _safe_url(observation["image_url"], _IMAGE_HOSTS[provider])
        raw = await self._request(url, limit=self.max_download_bytes, image=True)
        if provider == "unsplash":
            tracking = _safe_url(observation["metadata"]["download_location"], {"api.unsplash.com"})
            await self._request(
                tracking,
                headers={
                    "Authorization": f"Client-ID {self.unsplash_access_key}",
                    "Accept-Version": "v1",
                },
                limit=100_000,
            )
        return raw
