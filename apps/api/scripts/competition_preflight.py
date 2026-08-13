"""Fail-closed readiness check for a blockchain-required CreatorProof demo.

`blockchain_acceptance.py` proves that transactions already landed. This command
answers the earlier question: is this process configured and connected such that
the next write *must* go to a chain, including the multi-party layer. It fails
on configuration and on live reachability, so "the prototype writes to a
blockchain" is a checked fact rather than an intention.

It prints no RPC credentials, private keys, media or tenant data.
"""

from __future__ import annotations

import json

from app.container import build_container
from app.core.config import Settings
from app.services.blockchain import deployment_manifest


def _gate(checks: list[dict], failures: list[str], *, name: str, ok: bool, detail: object) -> bool:
    checks.append({"check": name, "passed": bool(ok), "detail": detail})
    if not ok:
        failures.append(name)
    return bool(ok)


def run_preflight(settings: Settings) -> dict:
    container = build_container(settings)
    checks: list[dict] = []
    failures: list[str] = []
    warnings: list[str] = []

    _gate(
        checks,
        failures,
        name="PROOF_ANCHOR_MODE_IS_EXPLICITLY_EAS",
        ok=settings.proof_anchor_mode == "eas",
        detail={
            "proof_anchor_mode": settings.proof_anchor_mode,
            "why": "'auto' may resolve to a local Merkle receipt, which is not a blockchain.",
        },
    )
    _gate(
        checks,
        failures,
        name="CHAIN_REQUIRED",
        ok=settings.proof_require_chain is True,
        detail={"proof_require_chain": settings.proof_require_chain},
    )

    signer_status = container.signer.status()
    _gate(
        checks,
        failures,
        name="STATEMENT_SIGNING_KEY_IS_OPERATOR_MANAGED",
        ok=signer_status.get("key_source") == "CONFIGURED",
        detail={
            "key_source": signer_status.get("key_source"),
            "why": "A key derived per process cannot support an audit after a restart.",
        },
    )

    anchor = container.proof_anchor
    is_chain_anchor = hasattr(anchor, "preflight")
    _gate(
        checks,
        failures,
        name="EAS_PROVIDER_ACTIVE",
        ok=is_chain_anchor and bool(getattr(anchor, "available", False)),
        detail={
            "provider": getattr(anchor, "name", None),
            "reason": getattr(anchor, "unavailable_reason", None),
        },
    )

    preflight = (
        anchor.preflight() if is_chain_anchor else {"ready": False, "reason": "NOT_A_CHAIN_ANCHOR"}
    )
    _gate(
        checks,
        failures,
        name="CHAIN_REACHABLE_AND_SIGNER_FUNDED",
        ok=bool(preflight.get("ready")),
        detail={
            "reason": preflight.get("reason"),
            "network_label": preflight.get("network_label"),
            "chain_id": preflight.get("chain_id"),
            "attester_address": preflight.get("attester_address"),
            "attester_balance_wei": preflight.get("attester_balance_wei"),
            "finality_tag_supported": preflight.get("finality_tag_supported"),
        },
    )

    ledger = container.blockchain.status()
    _gate(
        checks,
        failures,
        name="PACKET_WRITES_ENABLED",
        ok=bool(ledger.get("chain_writes_enabled")),
        detail={"chain_writes_enabled": ledger.get("chain_writes_enabled")},
    )
    _gate(
        checks,
        failures,
        name="CHECKPOINT_WRITES_ENABLED",
        ok=bool(ledger.get("checkpoint_writes_enabled")),
        detail={
            "checkpoint_writes_enabled": ledger.get("checkpoint_writes_enabled"),
            "checkpoint_schema_configured": ledger.get("checkpoint_schema_configured"),
        },
    )

    # Multi-party layer. Disabling it is a legitimate deployment choice, but for
    # this profile it is the difference between a network and a single attester,
    # so an enabled-but-unconfigured state must fail rather than warn.
    counterparty_enabled = settings.blockchain_counterparty_attestation_enabled
    if not counterparty_enabled:
        warnings.append("COUNTERPARTY_ATTESTATION_DISABLED_SINGLE_ATTESTER_DEPLOYMENT")
        checks.append(
            {
                "check": "COUNTERPARTY_ATTESTATION_ENABLED",
                "passed": False,
                "advisory": True,
                "detail": {"enabled": False},
            }
        )
    else:
        capability = container.coattestations.capability()
        _gate(
            checks,
            failures,
            name="COUNTERPARTY_SIGNATURE_VERIFIER_AVAILABLE",
            ok=bool(capability["signature"]["available"]),
            detail=capability["signature"],
        )
        _gate(
            checks,
            failures,
            name="COUNTERPARTY_WRITES_ENABLED",
            ok=bool(ledger.get("counterparty_writes_enabled")),
            detail={
                "counterparty_writes_enabled": ledger.get("counterparty_writes_enabled"),
                "counterparty_schema_configured": ledger.get("counterparty_schema_configured"),
            },
        )
        registry = capability["member_registry"]
        _gate(
            checks,
            failures,
            name="MEMBER_REGISTRY_READABLE",
            ok=bool(registry.get("configured") and registry.get("reason") is None),
            detail=registry,
        )
        _gate(
            checks,
            failures,
            name="MEMBER_REGISTRY_HAS_AN_ACTIVE_MEMBER",
            ok=bool((registry.get("active_member_count") or 0) > 0),
            detail={"active_member_count": registry.get("active_member_count")},
        )
        _gate(
            checks,
            failures,
            name="COUNTERPARTY_MEMBERSHIP_ENFORCED",
            ok=settings.counterparty_membership_required is True,
            detail={"counterparty_membership_required": settings.counterparty_membership_required},
        )

    if settings.eas_finality_policy == "confirmation_depth":
        warnings.append("FINALITY_POLICY_IS_CONFIRMATION_DEPTH_DEVELOPMENT_ONLY")
    if not settings.eas_expected_contract_code_sha256:
        warnings.append("EAS_CONTRACT_BYTECODE_NOT_PINNED")
    if not settings.eas_clearance_receipt_address:
        warnings.append("CLEARANCE_RECEIPT_CONTRACT_NOT_CONFIGURED")

    return {
        "schema": "creatorproof.competition_preflight.v1",
        "ready": not failures,
        "failures": failures,
        "warnings": warnings,
        "deployment_id": ledger.get("deployment_id"),
        "deployment_manifest": deployment_manifest(settings),
        "checks": checks,
        "next_step": (
            "Run scripts.blockchain_acceptance to reconcile real confirmed transactions."
            if not failures
            else "Fix every failed check; this deployment must not be presented as chain-backed."
        ),
        "claim_boundary": (
            "Readiness proves this process will publish 32-byte commitments to the configured "
            "chain. It does not prove authorship, ownership, non-infringement, or that any "
            "counterparty decision is correct."
        ),
    }


def main() -> int:
    try:
        result = run_preflight(Settings())
    except Exception as exc:
        result = {
            "schema": "creatorproof.competition_preflight.v1",
            "ready": False,
            "failures": [f"PREFLIGHT_FAILED:{type(exc).__name__}"],
        }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("ready") else 1


if __name__ == "__main__":
    raise SystemExit(main())
