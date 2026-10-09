"""Disposable eBay API fixture; never contacts eBay or reads live credentials.

Run with the API Python environment and FRONTEND_FIXTURE_DIR set to a temporary
directory. It reuses the isolated Phase 1 API and procedural reference image.
"""

import os
import runpy
from pathlib import Path

import httpx
import uvicorn

fixture = runpy.run_path(str(Path(__file__).with_name("phase1-fixture-api.py")))
app = fixture["app"]
root = fixture["root"]
source = app.state.container.marketplaces
source.ebay_client_id = "ebay-fixture-client"
source.ebay_client_secret = "ebay-fixture-secret"


def respond(request):
    if request.method == "POST":
        return httpx.Response(
            200,
            json={
                "access_token": "ebay-fixture-token",
                "expires_in": 7200,
                "token_type": "Application Access Token",
            },
        )
    if request.url.host == "i.ebayimg.com":
        return httpx.Response(
            200,
            headers={"Content-Type": "image/png"},
            content=(root / "artwork.png").read_bytes(),
        )
    if request.url.params.get("q") == "invalid-key":
        return httpx.Response(403)
    rows = (
        []
        if request.url.params.get("q") == "no-photos"
        else [
            {
                "itemId": "v1|123456789012|0",
                "title": "Sandbox artwork listing",
                "itemWebUrl": "https://sandbox.ebay.com/itm/123456789012",
                "image": {"imageUrl": "https://i.ebayimg.com/images/fixture.png"},
                "seller": {"username": "fixture-seller"},
                "itemLocation": {"country": "US"},
            }
        ]
    )
    return httpx.Response(200, json={"itemSummaries": rows})


source.transport = httpx.MockTransport(respond)
if __name__ == "__main__":
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=int(os.environ.get("FRONTEND_FIXTURE_PORT", "8011")),
        access_log=False,
    )
