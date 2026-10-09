import socket
import urllib.error
import urllib.request

import pytest

from app.services.safe_http import _NoRedirect, _resolve


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "http://user:password@example.com/",
        "ftp://example.com/",
    ],
)
def test_invalid_outbound_urls_rejected(url):
    with pytest.raises(ValueError):
        _resolve(url, allow_private=False)


@pytest.mark.parametrize("ip", ["127.0.0.1", "10.0.0.1", "169.254.169.254", "::1", "0.0.0.0"])
def test_private_and_reserved_dns_answers_rejected(monkeypatch, ip):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **k: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 80)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 80)),
        ],
    )
    with pytest.raises(ValueError, match="PRIVATE_HOST_BLOCKED"):
        _resolve("http://public-looking.example/image", allow_private=False)


def test_external_to_internal_redirect_is_never_followed():
    request = urllib.request.Request("https://public.example/webhook")
    with pytest.raises(urllib.error.HTTPError, match="Redirect blocked"):
        _NoRedirect().redirect_request(request, None, 302, "redirect", {}, "http://127.0.0.1/")
