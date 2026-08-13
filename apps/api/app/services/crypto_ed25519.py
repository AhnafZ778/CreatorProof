"""Ed25519 (RFC 8032) signing and verification.

The optional ``cryptography`` package is used when it is installed. The pure
Python fallback exists so the independent offline verifier keeps working on a
judge's or auditor's machine with nothing but a standard interpreter, which is
the whole point of publishing a verifier.
"""

from __future__ import annotations

import hashlib
import secrets

_P = 2**255 - 19
_L = 2**252 + 27742317777372353535851937790883648493
_D = (-121665 * pow(121666, _P - 2, _P)) % _P
_I = pow(2, (_P - 1) // 4, _P)

try:  # pragma: no cover - exercised only when the optional dependency is present
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey,
        Ed25519PublicKey,
    )

    _HAVE_CRYPTOGRAPHY = True
except Exception:  # pragma: no cover - fallback path
    _HAVE_CRYPTOGRAPHY = False


def _sha512(data: bytes) -> bytes:
    return hashlib.sha512(data).digest()


def _sha512_int(data: bytes) -> int:
    return int.from_bytes(_sha512(data), "little")


def _x_recover(y: int) -> int:
    xx = (y * y - 1) * pow(_D * y * y + 1, _P - 2, _P)
    x = pow(xx, (_P + 3) // 8, _P)
    if (x * x - xx) % _P != 0:
        x = (x * _I) % _P
    if x % 2 != 0:
        x = _P - x
    return x


_BY = (4 * pow(5, _P - 2, _P)) % _P
_BX = _x_recover(_BY)
_B = (_BX % _P, _BY % _P, 1, (_BX * _BY) % _P)


def _point_add(p: tuple[int, int, int, int], q: tuple[int, int, int, int]):
    x1, y1, z1, t1 = p
    x2, y2, z2, t2 = q
    a = ((y1 - x1) * (y2 - x2)) % _P
    b = ((y1 + x1) * (y2 + x2)) % _P
    c = (2 * t1 * t2 * _D) % _P
    d = (2 * z1 * z2) % _P
    e, f, g, h = b - a, d - c, d + c, b + a
    return ((e * f) % _P, (g * h) % _P, (f * g) % _P, (e * h) % _P)


def _scalar_mult(p: tuple[int, int, int, int], e: int):
    q = (0, 1, 1, 0)
    while e > 0:
        if e & 1:
            q = _point_add(q, p)
        p = _point_add(p, p)
        e >>= 1
    return q


def _compress(p: tuple[int, int, int, int]) -> bytes:
    x, y, z, _ = p
    inv_z = pow(z, _P - 2, _P)
    x = (x * inv_z) % _P
    y = (y * inv_z) % _P
    return int.to_bytes(y | ((x & 1) << 255), 32, "little")


def _decompress(data: bytes):
    value = int.from_bytes(data, "little")
    sign = value >> 255
    y = value & ((1 << 255) - 1)
    x = _x_recover(y)
    if x & 1 != sign:
        x = _P - x
    return (x, y, 1, (x * y) % _P)


def _secret_scalar(seed: bytes) -> tuple[int, bytes]:
    digest = _sha512(seed)
    head = bytearray(digest[:32])
    head[0] &= 248
    head[31] &= 127
    head[31] |= 64
    return int.from_bytes(head, "little"), digest[32:]


def generate_seed() -> bytes:
    return secrets.token_bytes(32)


def public_key_from_seed(seed: bytes) -> bytes:
    if len(seed) != 32:
        raise ValueError("Ed25519 seed must be 32 bytes")
    if _HAVE_CRYPTOGRAPHY:  # pragma: no cover - depends on optional dependency
        from cryptography.hazmat.primitives import serialization

        return (
            Ed25519PrivateKey.from_private_bytes(seed)
            .public_key()
            .public_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PublicFormat.Raw,
            )
        )
    scalar, _ = _secret_scalar(seed)
    return _compress(_scalar_mult(_B, scalar))


def sign(seed: bytes, message: bytes) -> bytes:
    if len(seed) != 32:
        raise ValueError("Ed25519 seed must be 32 bytes")
    if _HAVE_CRYPTOGRAPHY:  # pragma: no cover - depends on optional dependency
        return Ed25519PrivateKey.from_private_bytes(seed).sign(message)
    scalar, prefix = _secret_scalar(seed)
    public = _compress(_scalar_mult(_B, scalar))
    r = _sha512_int(prefix + message) % _L
    big_r = _compress(_scalar_mult(_B, r))
    k = _sha512_int(big_r + public + message) % _L
    s = (r + k * scalar) % _L
    return big_r + int.to_bytes(s, 32, "little")


def verify(public_key: bytes, message: bytes, signature: bytes) -> bool:
    if len(public_key) != 32 or len(signature) != 64:
        return False
    if _HAVE_CRYPTOGRAPHY:  # pragma: no cover - depends on optional dependency
        try:
            Ed25519PublicKey.from_public_bytes(public_key).verify(signature, message)
            return True
        except Exception:
            return False
    try:
        big_r = signature[:32]
        s = int.from_bytes(signature[32:], "little")
        if s >= _L:
            return False
        a = _decompress(public_key)
        k = _sha512_int(big_r + public_key + message) % _L
        left = _scalar_mult(_B, s)
        right = _point_add(_decompress(big_r), _scalar_mult(a, k))
        return _compress(left) == _compress(right)
    except Exception:
        return False
