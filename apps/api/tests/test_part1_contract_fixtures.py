import json
from pathlib import Path

FIXTURE_PATH = Path("tests/fixtures/part1/packet-scenarios.v1.json")


def _scenarios():
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    assert payload["schema"] == "creatorproof.part1_packet_fixture_set.v1"
    return payload["scenarios"]


def test_part1_handoff_has_all_ten_named_scenarios():
    scenarios = _scenarios()

    assert len(scenarios) == 10
    assert len({scenario["id"] for scenario in scenarios}) == 10
    assert all(scenario["expectation"] for scenario in scenarios)
    assert all(
        scenario["source_rights"]["state"]
        in {"OWNED", "AUTHORIZED", "LICENSED", "PUBLIC_DOMAIN_VERIFIED"}
        for scenario in scenarios
    )


def test_incomplete_or_degraded_scope_never_passes():
    for scenario in _scenarios():
        fragment = scenario["expected_packet_fragment"]
        scope = fragment.get("scope") or {}
        decision = fragment.get("decision") or {}
        if scope.get("coverage_status") in {"PARTIAL", "DEGRADED", "TRUNCATED", "FAILED"}:
            assert decision.get("policy_action") != "PASS_BY_POLICY"
            assert decision.get("match_status") != "NO_MATCH_IN_CHECKED_SOURCES"


def test_missing_provenance_fixture_never_implies_human_origin():
    scenario = next(
        item for item in _scenarios() if item["id"] == "absent-c2pa-detector-unavailable"
    )
    serialized = json.dumps(scenario).casefold()

    assert "absence_does_not_establish_human_origin" in serialized
    assert "human-made" in scenario["expectation"].casefold()
    assert (
        scenario["expected_packet_fragment"]["synthetic_origin"]["negative_clearance_supported"]
        is False
    )


def test_style_only_fixture_cannot_create_copy_match():
    scenario = next(
        item for item in _scenarios() if item["id"] == "creator-profile-resemblance-no-copy"
    )
    fragment = scenario["expected_packet_fragment"]

    assert fragment["decision"]["match_status"] == "NO_MATCH_IN_CHECKED_SOURCES"
    assert fragment["style_analysis"]["decision"]["review_recommended"] is True


def test_disputed_rights_fixture_cannot_authorize_use():
    scenario = next(item for item in _scenarios() if item["id"] == "disputed-rights-record")
    decision = scenario["expected_packet_fragment"]["decision"]

    assert decision["rights_path"] == "DISPUTED"
    assert decision["policy_action"] != "PASS_BY_POLICY"
