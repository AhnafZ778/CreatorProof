import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.domain.enums import MatchStatus
from app.services.evidence import _policy

PAYLOAD = json.loads(Path("tests/fixtures/part1/policy-cases.v1.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", PAYLOAD["cases"], ids=lambda case: case["id"])
def test_policy_golden_fixture(case):
    inputs = case["input"]
    work = SimpleNamespace(**inputs["work"]) if inputs["work"] else None

    action, rights_path, reasons = _policy(
        MatchStatus(inputs["match_status"]),
        work,
        inputs["intended_use"],
        coverage_status=inputs["coverage_status"],
    )

    assert str(action) == case["expected"]["action"]
    assert str(rights_path) == case["expected"]["rights_path"]
    assert case["expected"]["reason"] in reasons
