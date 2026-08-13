"""RFC 8785 JSON Canonicalization Scheme.

Evidence Statement v2 is hashed and signed over these bytes, so a Python signer
and a TypeScript verifier must agree byte for byte. The stricter value profile
below rejects the ambiguity that would otherwise make two implementations
disagree: NaN, infinity, duplicate keys and non-finite numbers.
"""

from __future__ import annotations

import hashlib
import math
import re
from typing import Any

_ESCAPES = {
    0x08: "\\b",
    0x09: "\\t",
    0x0A: "\\n",
    0x0C: "\\f",
    0x0D: "\\r",
    0x22: '\\"',
    0x5C: "\\\\",
}

_REPR_PATTERN = re.compile(r"^(\d+)(?:\.(\d+))?(?:e([+-]\d+))?$")


class CanonicalizationError(ValueError):
    """The value cannot be represented deterministically."""


def _escape_string(value: str) -> str:
    out = ['"']
    for char in value:
        code = ord(char)
        escape = _ESCAPES.get(code)
        if escape is not None:
            out.append(escape)
        elif code < 0x20:
            out.append(f"\\u{code:04x}")
        else:
            out.append(char)
    out.append('"')
    return "".join(out)


def _digits_and_exponent(value: float) -> tuple[str, int]:
    """Return significant digits and the decimal exponent ``n`` where value = 0.digits × 10ⁿ."""
    text = repr(value)
    match = _REPR_PATTERN.match(text)
    if match is None:  # pragma: no cover - repr of a finite positive float always matches
        raise CanonicalizationError(f"Unsupported numeric representation: {text}")
    integer_part, fraction_part, exponent_part = match.groups()
    fraction_part = fraction_part or ""
    exponent = int(exponent_part) if exponent_part else 0
    combined = (integer_part + fraction_part).lstrip("0")
    leading_zeros = len(integer_part + fraction_part) - len(combined)
    n = len(integer_part) + exponent - leading_zeros
    return combined.rstrip("0") or "0", n


def format_number(value: int | float) -> str:
    """Serialize a number using the ECMAScript ``Number::toString`` rules JCS requires."""
    if isinstance(value, bool):
        raise CanonicalizationError("Booleans are not numbers")
    if isinstance(value, int):
        return str(value)
    number = float(value)
    if math.isnan(number) or math.isinf(number):
        raise CanonicalizationError("NaN and Infinity cannot be canonicalized")
    if number == 0:
        return "0"
    negative = number < 0
    digits, n = _digits_and_exponent(abs(number))
    k = len(digits)
    if k <= n <= 21:
        rendered = digits + "0" * (n - k)
    elif 0 < n <= 21:
        rendered = f"{digits[:n]}.{digits[n:]}"
    elif -6 < n <= 0:
        rendered = "0." + "0" * (-n) + digits
    else:
        exponent = n - 1
        sign = "+" if exponent >= 0 else "-"
        mantissa = digits if k == 1 else f"{digits[0]}.{digits[1:]}"
        rendered = f"{mantissa}e{sign}{abs(exponent)}"
    return f"-{rendered}" if negative else rendered


def _sort_key(key: str) -> bytes:
    # JCS orders members by their UTF-16 code units, which differs from Python's
    # default code-point ordering for characters outside the basic plane.
    return key.encode("utf-16-be", errors="surrogatepass")


def _serialize(value: Any, out: list[str]) -> None:
    if value is None:
        out.append("null")
    elif value is True:
        out.append("true")
    elif value is False:
        out.append("false")
    elif isinstance(value, str):
        out.append(_escape_string(value))
    elif isinstance(value, int | float):
        out.append(format_number(value))
    elif isinstance(value, list | tuple):
        out.append("[")
        for index, item in enumerate(value):
            if index:
                out.append(",")
            _serialize(item, out)
        out.append("]")
    elif isinstance(value, dict):
        keys = list(value.keys())
        for key in keys:
            if not isinstance(key, str):
                raise CanonicalizationError("Object keys must be strings")
        if len(set(keys)) != len(keys):
            raise CanonicalizationError("Duplicate object keys are not canonicalizable")
        out.append("{")
        for index, key in enumerate(sorted(keys, key=_sort_key)):
            if index:
                out.append(",")
            out.append(_escape_string(key))
            out.append(":")
            _serialize(value[key], out)
        out.append("}")
    else:
        raise CanonicalizationError(f"Unsupported type for canonical JSON: {type(value).__name__}")


def canonicalize(value: Any) -> bytes:
    out: list[str] = []
    _serialize(value, out)
    return "".join(out).encode("utf-8")


def canonical_digest(value: Any) -> str:
    return hashlib.sha256(canonicalize(value)).hexdigest()
