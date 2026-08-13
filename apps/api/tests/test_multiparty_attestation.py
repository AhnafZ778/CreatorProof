"""Multi-party co-attestation: signature, membership, binding and anchoring gates.

These tests deliberately sign with a real secp256k1 key rather than stubbing the
verifier, because the whole point of the feature is that CreatorProof cannot
produce the artifact by itself.
"""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.container import build_container, initialize_database
from app.core.config import Settings
from app.domain.enums import AnchorStatus
from app.domain.platform import (
    BlockchainCommitmentType,
    CounterpartyAttestationState,
    CounterpartyDecision,
    NetworkMemberRole,
    NetworkMemberStatus,
)
from app.models import CounterpartyAttestation, NetworkMember, Scan
from app.providers.contracts import ProofReceipt
from app.providers.counterparty_signature import Eip712CounterpartyVerifier
from app.services.blockchain import BlockchainAnchorService
from app.services.coattestation import CoAttestationError, CoAttestationService, body_hash

eth_account = pytest.importorskip("eth_account")
Account = eth_account.Account

MEMBER_REGISTRY = "0x" + "ab" * 20
PLATFORM_UID = "0x" + "77" * 32
PACKET_HASH = "9f" * 32
CHAIN_ID = 31337
SIGNER_KEY = "0x" + "11" * 32


class _FakeChainProvider:
    """Enough of the EAS provider to exercise durable queueing, nothing more."""

    name = "ethereum-attestation-service-onchain-v1"

    def __init__(self):
        self.anchored: list[tuple[str, str | None]] = []

    def status(self):
        return {
            "scope": "PUBLIC_EVM_ATTESTATION",
            "available": True,
            "live_write_ready": True,
        }

    def anchor(
        self,
        commitment_hash,
        *,
        context=None,
        commitment_type=None,
        on_transaction_prepared=None,
    ):
        ref_uid = (context or {}).get("ref_uid")
        self.anchored.append((commitment_hash, ref_uid))
        if on_transaction_prepared is not None:
            on_transaction_prepared(
                {
                    "transaction_hash": "0x" + "12" * 32,
                    "signed_transaction_hex": "0x02aabb",
                    "nonce": 1,
                    "chain_id": CHAIN_ID,
                    "ref_uid": ref_uid,
                }
            )
        return ProofReceipt(
            status=AnchorStatus.ANCHORED,
            provider=self.name,
            receipt={
                "transaction_hash": "0x" + "12" * 32,
                "attestation_uid": "0x" + "34" * 32,
                "commitment_hash_sha256": commitment_hash,
                "coattestation_hash_sha256": commitment_hash,
                "ref_uid": ref_uid,
                "anchor_conditions_met": True,
            },
        )


class _StubRegistry:
    """Stands in for the on-chain registry so tests do not need an RPC endpoint."""

    name = "stub-member-registry"

    def __init__(self, *, configured=True, status=NetworkMemberStatus.ACTIVE, readable=True):
        self.configured = configured
        self._status = status
        self._readable = readable

    def lookup(self, address):
        if not self._readable:
            return {"checked": False, "reason": "MEMBER_REGISTRY_READ_FAILED:TimeoutError"}
        return {
            "checked": True,
            "reason": None,
            "address": address.lower(),
            "status": str(self._status),
            "active": self._status == NetworkMemberStatus.ACTIVE,
            "role": str(NetworkMemberRole.BRAND),
            "org_id": "00" * 32,
        }

    def status(self):
        return {"provider": self.name, "configured": self.configured, "reason": None}


@pytest.fixture
def env(tmp_path):
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'network.db'}",
        storage_root=tmp_path / "objects",
        job_backend="inline",
        dev_api_key="test-api-key-123",
        proof_log_path=tmp_path / "proof-log.jsonl",
        proof_anchor_mode="none",
        sscd_model_path=tmp_path / "models" / "sscd-not-installed.pt",
        style_provider="diagnostic",
        synthetic_detector="off",
        synthetic_policy_mode="INFORMATIONAL",
        c2pa_mode="off",
        visible_ai_marker_mode="off",
        copy_retrieval_requirement="BASELINE_ALLOWED",
        eas_chain_id=CHAIN_ID,
        eas_contract_address="0x" + "11" * 20,
        eas_schema_uid="0x" + "22" * 32,
        eas_checkpoint_schema_uid="0x" + "23" * 32,
        eas_coattestation_schema_uid="0x" + "24" * 32,
        eas_required_attester_address="0x" + "44" * 20,
        eas_member_registry_address=MEMBER_REGISTRY,
    )
    container = build_container(settings)
    initialize_database(container)
    provider = _FakeChainProvider()
    blockchain = BlockchainAnchorService(
        session_factory=container.database.system_session,
        provider=provider,
        transparency=container.transparency,
        settings=settings,
        worker_id="test-worker",
    )
    service = CoAttestationService(
        settings=settings,
        blockchain=blockchain,
        verifier=Eip712CounterpartyVerifier(
            domain_name=settings.counterparty_attestation_domain_name,
            domain_version=settings.counterparty_attestation_domain_version,
            chain_id=CHAIN_ID,
            verifying_contract=MEMBER_REGISTRY,
        ),
        member_registry=_StubRegistry(),
        signer=container.signer,
        transparency=container.transparency,
    )
    holder = SimpleNamespace(
        container=container,
        settings=settings,
        provider=provider,
        blockchain=blockchain,
        service=service,
        tenant_id=settings.dev_tenant_id,
    )
    try:
        yield holder
    finally:
        container.database.engine.dispose()


def _make_scan(env, *, attestation_uid: str | None = PLATFORM_UID) -> Scan:
    db = env.container.database.system_session()
    try:
        scan = Scan(
            id="scn_multiparty_1",
            tenant_id=env.tenant_id,
            idempotency_key="multiparty-1",
            catalog_id="cat_demo",
            intended_use="social_post",
            candidate_sha256="aa" * 32,
            candidate_phash="0" * 16,
            candidate_storage_key="scans/demo/candidate.bin",
            evidence_packet={
                "proof": {
                    "packet_hash_sha256": PACKET_HASH,
                    "receipt": ({"attestation_uid": attestation_uid} if attestation_uid else {}),
                }
            },
        )
        db.add(scan)
        db.commit()
        db.refresh(scan)
        db.expunge(scan)
        return scan
    finally:
        db.close()


def _enroll(env, address: str, *, status=NetworkMemberStatus.ACTIVE) -> None:
    db = env.container.database.system_session()
    try:
        db.add(
            NetworkMember(
                tenant_id=env.tenant_id,
                address=address.lower(),
                org_id="brand-acme",
                display_name="Acme Brand",
                role=str(NetworkMemberRole.BRAND),
                status=str(status),
            )
        )
        db.commit()
    finally:
        db.close()


def _sign(service, body: dict, key: str = SIGNER_KEY) -> str:
    from eth_account.messages import encode_typed_data

    from app.providers.counterparty_signature import TYPES

    payload = service.verifier.typed_data(body_hash(body))
    message = encode_typed_data(
        domain_data=payload["domain"],
        message_types=TYPES,
        message_data=payload["message"],
    )
    return Account.sign_message(message, private_key=key).signature.hex()


def _challenge(env, scan, *, address: str) -> dict:
    db = env.container.database.system_session()
    try:
        return env.service.challenge(
            db,
            scan=scan,
            signer_address=address,
            party_org_id="brand-acme",
            party_role=str(NetworkMemberRole.BRAND),
            decision=str(CounterpartyDecision.ACKNOWLEDGED),
        )
    finally:
        db.close()


def _record(env, scan, body, signature):
    db = env.container.database.system_session()
    try:
        return env.service.record(db, scan=scan, body=body, signature=signature)
    finally:
        db.close()


def test_counterparty_signature_is_recorded_and_queued_with_ref_uid_binding(env):
    """The happy path must produce a commitment CreatorProof could not fake alone."""
    account = Account.from_key(SIGNER_KEY)
    _enroll(env, account.address)
    scan = _make_scan(env)

    challenge = _challenge(env, scan, address=account.address)
    assert challenge["body"]["platform_attestation_uid"] == PLATFORM_UID.lower()
    assert challenge["typed_data"]["domain"]["chainId"] == CHAIN_ID
    assert challenge["typed_data"]["domain"]["verifyingContract"] == MEMBER_REGISTRY

    recorded = _record(env, scan, challenge["body"], _sign(env.service, challenge["body"]))

    assert recorded["signer_address"] == account.address.lower()
    assert recorded["state"] == str(CounterpartyAttestationState.ANCHOR_PENDING)
    assert recorded["checks"]["body_hash_matches_body"] is True
    assert recorded["checks"]["binds_platform_attestation"] is True
    assert recorded["public_chain"]["job_id"]

    while env.blockchain.dispatch_once():
        pass
    # Only the 32-byte digest reaches the chain, and it carries the platform UID
    # so the two attestations are provably about the same evidence packet.
    assert (recorded["body_hash_sha256"], PLATFORM_UID.lower()) in env.provider.anchored


def test_body_hash_is_independent_of_key_order(env):
    """A reviewer re-serializing the body must arrive at the same digest."""
    account = Account.from_key(SIGNER_KEY)
    _enroll(env, account.address)
    scan = _make_scan(env)
    body = _challenge(env, scan, address=account.address)["body"]

    reordered = dict(reversed(list(body.items())))

    assert body_hash(reordered) == body_hash(body)


def test_edited_body_is_refused_because_the_signature_no_longer_covers_it(env):
    account = Account.from_key(SIGNER_KEY)
    _enroll(env, account.address)
    scan = _make_scan(env)
    challenge = _challenge(env, scan, address=account.address)
    signature = _sign(env.service, challenge["body"])

    tampered = {
        **challenge["body"],
        "decision": str(CounterpartyDecision.ACCEPTED_FOR_PUBLICATION),
    }
    with pytest.raises(CoAttestationError) as excinfo:
        _record(env, scan, tampered, signature)

    assert excinfo.value.code == "SIGNER_ADDRESS_MISMATCH"


def test_signature_from_another_key_cannot_impersonate_the_named_signer(env):
    account = Account.from_key(SIGNER_KEY)
    _enroll(env, account.address)
    scan = _make_scan(env)
    challenge = _challenge(env, scan, address=account.address)

    other_key = "0x" + "22" * 32
    with pytest.raises(CoAttestationError) as excinfo:
        _record(env, scan, challenge["body"], _sign(env.service, challenge["body"], other_key))

    assert excinfo.value.code == "SIGNER_ADDRESS_MISMATCH"


def test_body_that_omits_the_platform_attestation_is_refused(env):
    """An unbound commitment could later be presented against a different packet."""
    account = Account.from_key(SIGNER_KEY)
    _enroll(env, account.address)
    scan = _make_scan(env)
    challenge = _challenge(env, scan, address=account.address)
    unbound = {**challenge["body"], "platform_attestation_uid": None}

    with pytest.raises(CoAttestationError) as excinfo:
        _record(env, scan, unbound, _sign(env.service, unbound))

    assert excinfo.value.code == "PLATFORM_ATTESTATION_BINDING_MISMATCH"


def test_body_shaped_for_another_deployment_is_refused(env):
    account = Account.from_key(SIGNER_KEY)
    _enroll(env, account.address)
    scan = _make_scan(env)
    challenge = _challenge(env, scan, address=account.address)
    foreign = {**challenge["body"], "chain_id": 1}

    with pytest.raises(CoAttestationError) as excinfo:
        _record(env, scan, foreign, _sign(env.service, foreign))

    assert excinfo.value.code == "BODY_DOES_NOT_MATCH_DEPLOYMENT"
    assert "chain_id" in excinfo.value.details["mismatched_fields"]


def test_extra_body_field_is_refused_rather_than_ignored(env):
    account = Account.from_key(SIGNER_KEY)
    _enroll(env, account.address)
    scan = _make_scan(env)
    challenge = _challenge(env, scan, address=account.address)
    padded = {**challenge["body"], "note": "please approve"}

    with pytest.raises(CoAttestationError) as excinfo:
        _record(env, scan, padded, _sign(env.service, padded))

    assert excinfo.value.code == "BODY_SHAPE_MISMATCH"


def test_stale_signature_is_refused(env):
    account = Account.from_key(SIGNER_KEY)
    _enroll(env, account.address)
    scan = _make_scan(env)
    challenge = _challenge(env, scan, address=account.address)
    stale_time = datetime.now(UTC) - timedelta(
        seconds=env.settings.counterparty_attestation_max_age_seconds + 120
    )
    stale = {**challenge["body"], "issued_at": stale_time.isoformat()}

    with pytest.raises(CoAttestationError) as excinfo:
        _record(env, scan, stale, _sign(env.service, stale))

    assert excinfo.value.code == "SIGNATURE_EXPIRED"


def test_suspended_member_cannot_co_attest(env):
    account = Account.from_key(SIGNER_KEY)
    _enroll(env, account.address)
    scan = _make_scan(env)
    env.service.member_registry = _StubRegistry(status=NetworkMemberStatus.SUSPENDED)

    with pytest.raises(CoAttestationError) as excinfo:
        _challenge(env, scan, address=account.address)

    assert excinfo.value.code == "MEMBER_NOT_ACTIVE"


def test_unreadable_registry_is_not_treated_as_permission(env):
    """An unknown answer from a configured registry must not become a yes."""
    account = Account.from_key(SIGNER_KEY)
    _enroll(env, account.address)
    scan = _make_scan(env)
    env.service.member_registry = _StubRegistry(readable=False)

    with pytest.raises(CoAttestationError) as excinfo:
        _challenge(env, scan, address=account.address)

    assert excinfo.value.code == "MEMBER_NOT_ACTIVE"
    membership = excinfo.value.details["membership"]
    assert membership["authority"] == "ON_CHAIN_REGISTRY_UNAVAILABLE"


def test_replayed_submission_does_not_create_a_second_commitment(env):
    account = Account.from_key(SIGNER_KEY)
    _enroll(env, account.address)
    scan = _make_scan(env)
    challenge = _challenge(env, scan, address=account.address)
    signature = _sign(env.service, challenge["body"])

    first = _record(env, scan, challenge["body"], signature)
    second = _record(env, scan, challenge["body"], signature)

    assert first["id"] == second["id"]
    db = env.container.database.system_session()
    try:
        rows = db.scalars(select(CounterpartyAttestation)).all()
    finally:
        db.close()
    assert len(rows) == 1


def test_withdrawal_marks_state_without_erasing_the_signature(env):
    account = Account.from_key(SIGNER_KEY)
    _enroll(env, account.address)
    scan = _make_scan(env)
    challenge = _challenge(env, scan, address=account.address)
    recorded = _record(env, scan, challenge["body"], _sign(env.service, challenge["body"]))

    db = env.container.database.system_session()
    try:
        row = db.get(CounterpartyAttestation, recorded["id"])
        withdrawn = env.service.withdraw(db, row, reason="campaign cancelled")
    finally:
        db.close()

    assert withdrawn["state"] == str(CounterpartyAttestationState.WITHDRAWN)
    assert withdrawn["signature"] == recorded["signature"]
    assert withdrawn["body_hash_sha256"] == recorded["body_hash_sha256"]


def test_signature_stored_before_a_crash_is_recovered_by_the_dispatcher(env):
    """A queue failure must not silently drop a counterparty's commitment."""
    account = Account.from_key(SIGNER_KEY)
    _enroll(env, account.address)
    scan = _make_scan(env)
    challenge = _challenge(env, scan, address=account.address)
    recorded = _record(env, scan, challenge["body"], _sign(env.service, challenge["body"]))

    db = env.container.database.system_session()
    try:
        row = db.get(CounterpartyAttestation, recorded["id"])
        row.anchor_job_id = None
        row.state = str(CounterpartyAttestationState.SIGNED)
        db.commit()
    finally:
        db.close()

    assert env.blockchain.reconcile_unanchored_counterparty_attestations() == 1

    db = env.container.database.system_session()
    try:
        row = db.get(CounterpartyAttestation, recorded["id"])
        assert row.anchor_job_id is not None
        assert str(row.state) == str(CounterpartyAttestationState.ANCHOR_PENDING)
    finally:
        db.close()


def test_capability_reports_counterparty_anchoring_readiness(env):
    capability = env.service.capability()

    assert capability["enabled"] is True
    assert capability["accepting_signatures"] is True
    assert capability["anchoring_ready"] is True
    assert capability["reasons"] == []
    assert env.blockchain.status()["counterparty_writes_enabled"] is True


def test_network_endpoints_collect_and_return_a_verifiable_commitment(env):
    """The HTTP surface a judge or a partner integration actually uses."""
    from fastapi.testclient import TestClient

    from app.main import create_app

    account = Account.from_key(SIGNER_KEY)
    scan = _make_scan(env)
    app = create_app(env.settings)
    with TestClient(app) as client:
        container = app.state.container
        container.blockchain = env.blockchain
        container.member_registry = env.service.member_registry
        container.coattestations = env.service
        env.service.blockchain = env.blockchain
        headers = {"X-API-Key": env.settings.dev_api_key}

        status = client.get("/v1/network/status", headers=headers)
        assert status.status_code == 200
        assert status.json()["accepting_signatures"] is True

        member = client.put(
            "/v1/network/members",
            headers=headers,
            json={
                "address": account.address,
                "org_id": "brand-acme",
                "display_name": "Acme Brand",
                "role": str(NetworkMemberRole.BRAND),
            },
        )
        assert member.status_code == 200
        assert member.json()["address"] == account.address.lower()

        challenge = client.post(
            "/v1/network/co-attestations/challenge",
            headers=headers,
            json={
                "scan_id": scan.id,
                "signer_address": account.address,
                "party_org_id": "brand-acme",
                "party_role": str(NetworkMemberRole.BRAND),
                "decision": str(CounterpartyDecision.ACCEPTED_FOR_PUBLICATION),
            },
        )
        assert challenge.status_code == 200
        body = challenge.json()["body"]

        submitted = client.post(
            "/v1/network/co-attestations",
            headers=headers,
            json={"scan_id": scan.id, "body": body, "signature": _sign(env.service, body)},
        )
        assert submitted.status_code == 201
        payload = submitted.json()
        assert payload["signer_address"] == account.address.lower()
        assert payload["decision"] == str(CounterpartyDecision.ACCEPTED_FOR_PUBLICATION)

        listed = client.get(
            "/v1/network/co-attestations", headers=headers, params={"scan_id": scan.id}
        )
        assert [item["id"] for item in listed.json()["items"]] == [payload["id"]]

        # The evidence packet's own proof surface must not change shape because a
        # counterparty signed; the network layer is additive.
        proof_status = client.get("/v1/proof/status", headers=headers)
        assert proof_status.json()["multi_party_attestation"]["enabled"] is True


def test_submission_is_refused_when_the_deployment_cannot_verify_signatures(env):
    from fastapi.testclient import TestClient

    from app.main import create_app

    account = Account.from_key(SIGNER_KEY)
    _enroll(env, account.address)
    scan = _make_scan(env)
    challenge = _challenge(env, scan, address=account.address)
    signature = _sign(env.service, challenge["body"])

    settings = env.settings.model_copy(update={"eas_member_registry_address": ""})
    app = create_app(settings)
    with TestClient(app) as client:
        headers = {"X-API-Key": settings.dev_api_key}
        status = client.get("/v1/network/status", headers=headers)
        assert status.json()["accepting_signatures"] is False
        assert "COUNTERPARTY_VERIFYING_CONTRACT_NOT_CONFIGURED" in status.json()["reasons"]

        refused = client.post(
            "/v1/network/co-attestations",
            headers=headers,
            json={"scan_id": scan.id, "body": challenge["body"], "signature": signature},
        )

    assert refused.status_code in (404, 409)


def test_missing_coattestation_schema_disables_only_the_counterparty_lane(env):
    """Packet anchoring must keep working when the third schema is unregistered."""
    settings = env.settings.model_copy(update={"eas_coattestation_schema_uid": ""})
    blockchain = BlockchainAnchorService(
        session_factory=env.container.database.system_session,
        provider=env.provider,
        transparency=env.container.transparency,
        settings=settings,
        worker_id="test-worker",
    )

    status = blockchain.status()

    assert status["chain_writes_enabled"] is True
    assert status["counterparty_writes_enabled"] is False
    assert (
        blockchain.enqueue_counterparty_attestation(
            body_hash="cd" * 32,
            attestation_id="cpa_missing_schema",
            tenant_id=env.tenant_id,
            scan_id="scn_multiparty_1",
            signer_address="0x" + "55" * 20,
            ref_uid=PLATFORM_UID,
        )
        is None
    )
    assert (
        blockchain.enqueue(
            commitment_hash="ce" * 32,
            commitment_type=BlockchainCommitmentType.EVIDENCE_PACKET,
            subject_type="scan",
            subject_id="scn_multiparty_1",
            tenant_id=env.tenant_id,
        )
        is not None
    )
