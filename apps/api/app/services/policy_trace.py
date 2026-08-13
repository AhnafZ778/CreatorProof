from __future__ import annotations

from typing import Any

from app.services.model_bundle import canonical_json_digest

POLICY_TRACE_SCHEMA = "creatorproof.policy_trace.v1"


def build_policy_trace(
    *,
    policy_version: str,
    inputs: dict[str, Any],
    outputs: dict[str, Any],
    matched_rule_codes: list[str],
    missing_facts: list[str] | None = None,
) -> dict:
    rules = list(dict.fromkeys(str(code) for code in matched_rule_codes))
    trace = {
        "schema": POLICY_TRACE_SCHEMA,
        "policy_version": policy_version,
        "inputs": inputs,
        "outputs": outputs,
        "matched_rule_codes": rules,
        "missing_facts": sorted(set(missing_facts or [])),
        "semantics": "DETERMINISTIC_POLICY_REPLAY_RECORD_NOT_LEGAL_ADVICE",
    }
    return {
        **trace,
        "trace_digest_sha256": canonical_json_digest(trace),
    }


def verify_policy_trace(trace: dict) -> bool:
    if trace.get("schema") != POLICY_TRACE_SCHEMA:
        return False
    expected = trace.get("trace_digest_sha256")
    material = {key: value for key, value in trace.items() if key != "trace_digest_sha256"}
    return isinstance(expected, str) and canonical_json_digest(material) == expected
