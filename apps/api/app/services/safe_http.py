"""Outbound HTTP with public-address pinning and redirects disabled."""

import http.client
import ipaddress
import socket
import urllib.error
import urllib.parse
import urllib.request


def _resolve(url: str, *, allow_private: bool) -> tuple[str, int, str]:
    parsed = urllib.parse.urlsplit(url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError("OUTBOUND_URL_INVALID")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    infos = socket.getaddrinfo(parsed.hostname, port, type=socket.SOCK_STREAM)
    addresses = sorted({info[4][0] for info in infos})
    if not addresses:
        raise ValueError("OUTBOUND_HOST_UNRESOLVED")
    if not allow_private and any(not ipaddress.ip_address(ip).is_global for ip in addresses):
        raise ValueError("OUTBOUND_PRIVATE_HOST_BLOCKED")
    return parsed.hostname, port, addresses[0]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, "Redirect blocked", headers, fp)


def safe_urlopen(request: urllib.request.Request, *, timeout: float, allow_private: bool = False):
    """Resolve once, validate every DNS answer, and connect to a fixed address.

    HTTP Host and HTTPS SNI/certificate verification still use the original host.
    Proxy environment variables are deliberately ignored so they cannot bypass
    the validated route. A redirect is a failure, never a second request.
    """
    host, port, address = _resolve(request.full_url, allow_private=allow_private)

    class PinnedHTTP(http.client.HTTPConnection):
        def connect(self):
            self.sock = socket.create_connection((address, port), self.timeout)

    class PinnedHTTPS(http.client.HTTPSConnection):
        def connect(self):
            self.sock = socket.create_connection((address, port), self.timeout)
            try:
                self.sock = self._context.wrap_socket(self.sock, server_hostname=host)
            except BaseException:
                self.sock.close()
                raise

    class HTTPHandler(urllib.request.HTTPHandler):
        def http_open(self, req):
            return self.do_open(PinnedHTTP, req)

    class HTTPSHandler(urllib.request.HTTPSHandler):
        def https_open(self, req):
            return self.do_open(PinnedHTTPS, req, context=self._context)

    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        _NoRedirect(),
        HTTPHandler(),
        HTTPSHandler(),
    )
    return opener.open(request, timeout=timeout)
