from app.services.policy_trace import build_policy_trace, verify_policy_trace


def _trace():
    return build_policy_trace(
        policy_version="policy-v1",
        inputs={"match_status": "NO_MATCH_IN_CHECKED_SOURCES", "coverage": "COMPLETE"},
        outputs={"policy_action": "PASS_BY_POLICY"},
        matched_rule_codes=[
            "NO_MATCH_IN_DECLARED_CATALOG",
            "NO_MATCH_IN_DECLARED_CATALOG",
            "PASS_IS_POLICY_NOT_COPYRIGHT_CLEARANCE",
        ],
    )


def test_policy_trace_is_deterministic_and_deduplicates_rules():
    first = _trace()
    second = _trace()

    assert first == second
    assert first["matched_rule_codes"] == [
        "NO_MATCH_IN_DECLARED_CATALOG",
        "PASS_IS_POLICY_NOT_COPYRIGHT_CLEARANCE",
    ]
    assert verify_policy_trace(first) is True


def test_policy_trace_detects_output_tampering():
    trace = _trace()
    trace["outputs"]["policy_action"] = "BLOCK"

    assert verify_policy_trace(trace) is False


def test_policy_version_changes_trace_identity():
    first = _trace()
    second = {**first, "policy_version": "policy-v2"}

    assert verify_policy_trace(second) is False
