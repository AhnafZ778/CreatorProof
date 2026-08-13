"""RFC 8785 JCS conformance.

If canonicalization drifts by a single byte, every previously signed statement
becomes unverifiable, so these vectors are deliberately pedantic.
"""

import json

import pytest

from app.services.canonical import canonical_digest, canonicalize


def test_object_keys_sort_by_utf16_code_unit():
    payload = {"b": 1, "a": 2, "\u00e4": 3, "A": 4}
    assert canonicalize(payload) == b'{"A":4,"a":2,"b":1,"\xc3\xa4":3}'


def test_nested_structures_and_arrays_preserve_array_order():
    payload = {"z": [3, 1, 2], "a": {"n": None, "t": True, "f": False}}
    assert canonicalize(payload) == b'{"a":{"f":false,"n":null,"t":true},"z":[3,1,2]}'


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0, "0"),
        (-0.0, "0"),
        (1, "1"),
        (1.0, "1"),
        (1.5, "1.5"),
        (1e21, "1e+21"),
        (1e-7, "1e-7"),
        (0.000001, "0.000001"),
        (333333333.33333329, "333333333.3333333"),
    ],
)
def test_numbers_use_ecmascript_serialization(value, expected):
    assert canonicalize({"n": value}) == f'{{"n":{expected}}}'.encode()


def test_control_characters_and_quotes_escape_exactly():
    payload = {"s": 'a"b\\c\nd\te\u0000f'}
    assert canonicalize(payload) == b'{"s":"a\\"b\\\\c\\nd\\te\\u0000f"}'


def test_non_ascii_is_emitted_as_utf8_not_escaped():
    assert canonicalize({"s": "\u00e9\u4e2d"}) == '{"s":"\u00e9\u4e2d"}'.encode()


def test_nan_and_infinity_are_rejected():
    for bad in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValueError):
            canonicalize({"n": bad})


def test_digest_is_stable_across_input_key_order():
    left = {"alpha": 1, "beta": {"x": [1, 2], "y": "z"}}
    right = json.loads('{"beta": {"y": "z", "x": [1, 2]}, "alpha": 1}')
    assert canonical_digest(left) == canonical_digest(right)
