"""Minimal CBOR and COSE_Sign1 (RFC 9052) encoding for Evidence Statement v2.

Only the subset needed for a detached-header EdDSA signature is implemented.
Keeping it dependency-free means an auditor can verify a statement with a plain
Python interpreter, which is a requirement of the offline verifier.
"""

from __future__ import annotations

COSE_SIGN1_TAG = 18
_ALG_EDDSA = -8
_HEADER_ALG = 1
_HEADER_KID = 4


def _encode_head(major: int, length: int) -> bytes:
    prefix = major << 5
    if length < 24:
        return bytes([prefix | length])
    if length < 0x100:
        return bytes([prefix | 24, length])
    if length < 0x10000:
        return bytes([prefix | 25]) + length.to_bytes(2, "big")
    if length < 0x100000000:
        return bytes([prefix | 26]) + length.to_bytes(4, "big")
    return bytes([prefix | 27]) + length.to_bytes(8, "big")


def encode(value) -> bytes:
    if value is None:
        return b"\xf6"
    if value is True:
        return b"\xf5"
    if value is False:
        return b"\xf4"
    if isinstance(value, int):
        if value >= 0:
            return _encode_head(0, value)
        return _encode_head(1, -value - 1)
    if isinstance(value, bytes | bytearray):
        return _encode_head(2, len(value)) + bytes(value)
    if isinstance(value, str):
        encoded = value.encode("utf-8")
        return _encode_head(3, len(encoded)) + encoded
    if isinstance(value, list | tuple):
        return _encode_head(4, len(value)) + b"".join(encode(item) for item in value)
    if isinstance(value, dict):
        # Deterministic map ordering keeps the signed bytes reproducible.
        items = sorted(value.items(), key=lambda pair: encode(pair[0]))
        body = b"".join(encode(key) + encode(item) for key, item in items)
        return _encode_head(5, len(items)) + body
    raise TypeError(f"Unsupported CBOR type: {type(value).__name__}")


def encode_tagged(tag: int, value) -> bytes:
    return _encode_head(6, tag) + encode(value)


def protected_header(algorithm: int = _ALG_EDDSA) -> bytes:
    return encode({_HEADER_ALG: algorithm})


def sig_structure(payload: bytes, *, protected: bytes, external_aad: bytes = b"") -> bytes:
    """Build the ``Signature1`` structure that is actually signed."""
    return encode(["Signature1", protected, external_aad, payload])


def build_sign1(*, payload: bytes, signature: bytes, kid: str) -> bytes:
    protected = protected_header()
    unprotected = {_HEADER_KID: kid.encode("utf-8")}
    return encode_tagged(COSE_SIGN1_TAG, [protected, unprotected, payload, signature])


def decode(data: bytes, offset: int = 0):
    """Decode a CBOR item. Returns ``(value, next_offset)``."""
    initial = data[offset]
    major = initial >> 5
    minor = initial & 0x1F
    offset += 1
    if minor < 24:
        length = minor
    elif minor == 24:
        length = data[offset]
        offset += 1
    elif minor == 25:
        length = int.from_bytes(data[offset : offset + 2], "big")
        offset += 2
    elif minor == 26:
        length = int.from_bytes(data[offset : offset + 4], "big")
        offset += 4
    elif minor == 27:
        length = int.from_bytes(data[offset : offset + 8], "big")
        offset += 8
    else:
        if initial == 0xF6:
            return None, offset
        if initial == 0xF5:
            return True, offset
        if initial == 0xF4:
            return False, offset
        raise ValueError("Unsupported CBOR simple value")

    if major == 0:
        return length, offset
    if major == 1:
        return -length - 1, offset
    if major == 2:
        return data[offset : offset + length], offset + length
    if major == 3:
        return data[offset : offset + length].decode("utf-8"), offset + length
    if major == 4:
        items = []
        for _ in range(length):
            item, offset = decode(data, offset)
            items.append(item)
        return items, offset
    if major == 5:
        result = {}
        for _ in range(length):
            key, offset = decode(data, offset)
            item, offset = decode(data, offset)
            result[key if not isinstance(key, bytes) else key.decode("utf-8", "replace")] = item
        return result, offset
    if major == 6:
        inner, offset = decode(data, offset)
        return inner, offset
    raise ValueError("Unsupported CBOR major type")


def parse_sign1(data: bytes) -> dict:
    """Return the parts of a COSE_Sign1 envelope needed for verification."""
    value, _ = decode(data)
    if not isinstance(value, list) or len(value) != 4:
        raise ValueError("Not a COSE_Sign1 structure")
    protected, unprotected, payload, signature = value
    kid = None
    if isinstance(unprotected, dict):
        raw_kid = unprotected.get(_HEADER_KID)
        if isinstance(raw_kid, bytes):
            kid = raw_kid.decode("utf-8", "replace")
        elif isinstance(raw_kid, str):
            kid = raw_kid
    return {
        "protected": protected,
        "kid": kid,
        "payload": payload,
        "signature": signature,
    }
