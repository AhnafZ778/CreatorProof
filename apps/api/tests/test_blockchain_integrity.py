from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.routes.proof import proof_status, subject_integrity
from app.container import build_container, initialize_database
from app.core.config import Settings
from app.core.security import AuthContext
from app.domain.enums import AnchorStatus
from app.domain.platform import (
    BlockchainAnchorJobState,
    BlockchainCommitmentType,
    CredentialScope,
    PrincipalRole,
    ScanLifecycleState,
)
from app.models import (
    BlockchainAnchorJob,
    EvidenceStatement,
    IntegrityEvent,
    OutboxEvent,
    Scan,
    TransparencyCheckpoint,
)
from app.providers.contracts import ProofReceipt
from app.services.blockchain import (
    BlockchainAnchorService,
    deployment_id,
    record_integrity_event,
    signer_lease_id,
)
from app.services.transparency import TransparencyLog


@pytest.fixture
def client(tmp_path):
    """A lightweight container fixture; these tests do not need an ASGI portal."""
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'blockchain.db'}",
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
    )
    container = build_container(settings)
    initialize_database(container)
    holder = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(container=container)))
    try:
        yield holder
    finally:
        container.database.engine.dispose()


class _FakeEAS:
    name = "fake-eas"

    def __init__(self):
        self.anchor_calls = 0
        self.reconcile_calls = 0

    def status(self):
        return {"is_blockchain": True, "scope": "PUBLIC_EVM_ATTESTATION"}

    def anchor(
        self,
        commitment_hash,
        *,
        context=None,
        commitment_type=None,
        on_transaction_prepared=None,
    ):
        self.anchor_calls += 1
        on_transaction_prepared(
            {
                "transaction_hash": "0x" + "12" * 32,
                "signed_transaction_hex": "0x02aabb",
                "nonce": 7,
                "chain_id": 84532,
            }
        )
        return ProofReceipt(
            status=AnchorStatus.ANCHORED,
            provider=self.name,
            receipt={
                "transaction_hash": "0x" + "12" * 32,
                "attestation_uid": "0x" + "34" * 32,
                "commitment_hash_sha256": commitment_hash,
                **(
                    {"checkpoint_hash_sha256": commitment_hash}
                    if str(commitment_type) == str(BlockchainCommitmentType.TRANSPARENCY_CHECKPOINT)
                    else {"packet_hash_sha256": commitment_hash}
                ),
                "anchor_scope": "PUBLIC_EVM_ATTESTATION_PACKET_HASH_ONLY",
                "anchor_conditions_met": True,
                "finalized": False,
            },
        )

    def reconcile(
        self,
        transaction_hash,
        expected_commitment_hash,
        expected_metadata=None,
        signed_transaction_hex=None,
    ):
        self.reconcile_calls += 1
        assert transaction_hash == "0x" + "12" * 32
        assert signed_transaction_hex == "0x02aabb"
        return ProofReceipt(
            status=AnchorStatus.ANCHORED,
            provider=self.name,
            receipt={
                "transaction_hash": transaction_hash,
                "attestation_uid": "0x" + "34" * 32,
                "commitment_hash_sha256": expected_commitment_hash,
                **(
                    {"checkpoint_hash_sha256": expected_commitment_hash}
                    if (expected_metadata or {}).get("commitment_type")
                    == str(BlockchainCommitmentType.TRANSPARENCY_CHECKPOINT)
                    else {"packet_hash_sha256": expected_commitment_hash}
                ),
                "anchor_scope": "PUBLIC_EVM_ATTESTATION_PACKET_HASH_ONLY",
                "anchor_conditions_met": True,
                "finalized": False,
            },
        )


def _service(client, provider):
    container = client.app.state.container
    settings = container.settings.model_copy(
        update={
            "eas_chain_id": 84532,
            "eas_contract_address": "0x" + "11" * 20,
            "eas_schema_uid": "0x" + "22" * 32,
            "eas_checkpoint_schema_uid": "0x" + "23" * 32,
            "eas_required_attester_address": "0x" + "44" * 20,
        }
    )
    return BlockchainAnchorService(
        session_factory=container.database.session_factory,
        provider=provider,
        transparency=container.transparency,
        settings=settings,
        worker_id="test-worker",
    )


class _ScopeOnlyEAS(_FakeEAS):
    name = "ethereum-attestation-service-onchain-v1"

    def status(self):
        return {"scope": "PUBLIC_EVM_ATTESTATION", "available": True}


def test_public_evm_scope_activates_durable_dispatch_without_name_heuristics(client):
    service = _service(client, _ScopeOnlyEAS())

    assert service.enabled is True
    assert (
        service.enqueue(
            commitment_hash="fe" * 32,
            commitment_type=BlockchainCommitmentType.EVIDENCE_PACKET,
            subject_type="scan",
            subject_id="scan-scope-only",
            tenant_id=client.app.state.container.settings.dev_tenant_id,
        )
        is not None
    )


def test_explicitly_unavailable_eas_provider_does_not_enable_chain_writes(client):
    provider = _ScopeOnlyEAS()
    provider.status = lambda: {
        "scope": "PUBLIC_EVM_ATTESTATION",
        "available": False,
    }
    service = _service(client, provider)

    assert service.enabled is False
    assert service.status()["chain_writes_enabled"] is False
    assert (
        service.enqueue(
            commitment_hash="fd" * 32,
            commitment_type=BlockchainCommitmentType.EVIDENCE_PACKET,
            subject_type="scan",
            subject_id="scan-disabled-provider",
            tenant_id=client.app.state.container.settings.dev_tenant_id,
        )
        is None
    )


def test_live_rpc_failure_is_truthful_without_disabling_the_durable_queue(client):
    provider = _ScopeOnlyEAS()
    provider.status = lambda: {
        "scope": "PUBLIC_EVM_ATTESTATION",
        "available": True,
        "configured": True,
        "live_write_ready": False,
        "live_write_reason": "EAS_RPC_NOT_CONNECTED",
        "checkpoint_configured": True,
    }
    service = _service(client, provider)

    status = service.status()

    assert status["provider_configured"] is True
    assert status["durable_queue_enabled"] is True
    assert status["chain_writes_configured"] is True
    assert status["chain_writes_enabled"] is False
    assert status["chain_writes_ready"] is False
    assert status["live_write_reason"] == "EAS_RPC_NOT_CONNECTED"
    assert (
        service.enqueue(
            commitment_hash="fc" * 32,
            commitment_type=BlockchainCommitmentType.EVIDENCE_PACKET,
            subject_type="scan",
            subject_id="scan-rpc-temporarily-down",
            tenant_id=client.app.state.container.settings.dev_tenant_id,
        )
        is not None
    )


def test_provider_exception_text_cannot_leak_rpc_credentials_into_public_receipts(client):
    class ExplodingEAS(_FakeEAS):
        def anchor(self, *_args, **_kwargs):
            raise RuntimeError("https://rpc.invalid/private-token")

    service = _service(client, ExplodingEAS())

    receipt = service.anchor_packet(
        packet_hash="fb" * 32,
        scan_id="scan-secret-error",
        tenant_id=client.app.state.container.settings.dev_tenant_id,
    )

    assert receipt.status == AnchorStatus.PENDING
    assert receipt.receipt["error_code"] == "BLOCKCHAIN_ANCHOR_EXCEPTION:RuntimeError"
    assert "private-token" not in str(receipt.receipt)


def test_proof_status_does_not_call_non_chain_provider_a_blockchain(client):
    container = client.app.state.container

    payload = proof_status(_auditor_auth(container), container)

    assert payload["scope"] == "NONE"
    assert payload["is_blockchain"] is False
    assert payload["chain_writes_enabled"] is False
    assert payload["transaction_ledger"]["chain_writes_enabled"] is False


def test_deployment_id_changes_with_every_trust_relevant_binding():
    baseline = Settings(
        eas_chain_id=84532,
        eas_contract_address="0x" + "11" * 20,
        eas_schema_uid="0x" + "22" * 32,
        eas_checkpoint_schema_uid="0x" + "23" * 32,
        eas_required_attester_address="0x" + "44" * 20,
        eas_expected_contract_code_sha256="55" * 32,
    )
    original = deployment_id(baseline)
    mutations = {
        "eas_chain_id": 8453,
        "eas_contract_address": "0x" + "66" * 20,
        "eas_schema_uid": "0x" + "67" * 32,
        "eas_checkpoint_schema_uid": "0x" + "68" * 32,
        "eas_schema_definition": "bytes32 evidenceHash",
        "eas_checkpoint_schema_definition": "bytes32 treeRoot",
        "eas_recipient": "0x" + "69" * 20,
        "eas_required_attester_address": "0x" + "70" * 20,
        "eas_expected_contract_code_sha256": "71" * 32,
        "eas_finality_policy": "safe",
    }
    for field, value in mutations.items():
        assert deployment_id(baseline.model_copy(update={field: value})) != original


def test_signer_lease_identity_uses_actual_account_and_chain_not_deployment_schema():
    settings = Settings(
        eas_chain_id=84532,
        eas_schema_uid="0x" + "22" * 32,
        eas_required_attester_address="0x" + "99" * 20,
    )
    provider = SimpleNamespace(
        chain_id=84532,
        attester_address="0x" + "44" * 20,
        required_attester_address="0x" + "99" * 20,
        status=lambda: {"chain_id": 84532, "attester_address": "0x" + "44" * 20},
    )

    lease = signer_lease_id(provider, settings)

    assert lease == signer_lease_id(
        provider,
        settings.model_copy(
            update={
                "eas_schema_uid": "0x" + "33" * 32,
                "eas_required_attester_address": "0x" + "88" * 20,
            }
        ),
    )
    assert lease != signer_lease_id(
        SimpleNamespace(
            chain_id=84532,
            attester_address="0x" + "45" * 20,
            status=lambda: {},
        ),
        settings,
    )
    assert lease != signer_lease_id(
        SimpleNamespace(
            chain_id=8453,
            attester_address="0x" + "44" * 20,
            status=lambda: {},
        ),
        settings,
    )


def test_deployment_rollover_isolates_claims_receipts_and_status_counts(client):
    provider = _FakeEAS()
    previous = _service(client, provider)
    previous_job_id = previous.enqueue(
        commitment_hash="da" * 32,
        commitment_type=BlockchainCommitmentType.EVIDENCE_PACKET,
        subject_type="scan",
        subject_id="scan-previous-deployment",
        tenant_id=client.app.state.container.settings.dev_tenant_id,
    )
    current = BlockchainAnchorService(
        session_factory=client.app.state.container.database.session_factory,
        provider=provider,
        transparency=client.app.state.container.transparency,
        settings=previous.settings.model_copy(update={"eas_schema_uid": "0x" + "66" * 32}),
        worker_id="current-deployment-worker",
    )
    current_job_id = current.enqueue(
        commitment_hash="db" * 32,
        commitment_type=BlockchainCommitmentType.EVIDENCE_PACKET,
        subject_type="scan",
        subject_id="scan-current-deployment",
        tenant_id=client.app.state.container.settings.dev_tenant_id,
    )

    status = current.status()

    assert status["states"] == {str(BlockchainAnchorJobState.PENDING): 1}
    assert current.process_job(previous_job_id) is False
    with pytest.raises(LookupError):
        current.receipt_for_job(previous_job_id)
    assert current.process_job(current_job_id) is True


def test_checkpoint_queue_is_disabled_without_a_distinct_checkpoint_schema(client):
    provider = _FakeEAS()
    configured = _service(client, provider)
    service = BlockchainAnchorService(
        session_factory=client.app.state.container.database.session_factory,
        provider=provider,
        transparency=client.app.state.container.transparency,
        settings=configured.settings.model_copy(update={"eas_checkpoint_schema_uid": ""}),
        worker_id="checkpoint-schema-test",
    )

    assert service.checkpoint_enabled is False
    assert service.status()["checkpoint_writes_enabled"] is False
    assert (
        service.enqueue_checkpoint({"checkpoint": {"tree_size": 1, "root_sha256": "dc" * 32}})
        is None
    )


def test_prepared_transaction_is_persisted_before_result(client):
    provider = _FakeEAS()
    service = _service(client, provider)
    receipt = service.anchor_packet(
        packet_hash="aa" * 32,
        scan_id="scan-proof",
        tenant_id=client.app.state.container.settings.dev_tenant_id,
    )

    assert receipt.status == AnchorStatus.ANCHORED
    db = client.app.state.container.database.session_factory()
    try:
        job = db.scalar(select(BlockchainAnchorJob))
        assert job.state == BlockchainAnchorJobState.CONFIRMED
        assert job.transaction_hash == "0x" + "12" * 32
        assert job.signed_transaction_hex == "0x02aabb"
        assert job.transaction_nonce == 7
    finally:
        db.close()


def test_existing_prepared_transaction_reconciles_without_new_nonce(client):
    provider = _FakeEAS()
    service = _service(client, provider)
    job_id = service.enqueue(
        commitment_hash="bb" * 32,
        commitment_type=BlockchainCommitmentType.EVIDENCE_PACKET,
        subject_type="scan",
        subject_id="scan-resume",
        tenant_id=client.app.state.container.settings.dev_tenant_id,
    )
    db = client.app.state.container.database.session_factory()
    try:
        job = db.get(BlockchainAnchorJob, job_id)
        job.state = BlockchainAnchorJobState.PREPARED
        job.transaction_hash = "0x" + "12" * 32
        job.signed_transaction_hex = "0x02aabb"
        db.commit()
    finally:
        db.close()

    assert service.process_job(job_id) is True
    assert provider.anchor_calls == 0
    assert provider.reconcile_calls == 1


def test_prepared_transaction_remains_reconcilable_after_attempt_budget_is_exhausted(client):
    provider = _FakeEAS()
    service = _service(client, provider)
    job_id = service.enqueue(
        commitment_hash="bc" * 32,
        commitment_type=BlockchainCommitmentType.EVIDENCE_PACKET,
        subject_type="scan",
        subject_id="scan-resume-after-budget",
        tenant_id=client.app.state.container.settings.dev_tenant_id,
    )
    db = client.app.state.container.database.session_factory()
    try:
        job = db.get(BlockchainAnchorJob, job_id)
        job.state = BlockchainAnchorJobState.PREPARED
        job.transaction_hash = "0x" + "12" * 32
        job.signed_transaction_hex = "0x02aabb"
        job.attempts = job.max_attempts
        db.commit()
        attempt_budget = job.max_attempts
    finally:
        db.close()

    assert service.process_job(job_id) is True

    db = client.app.state.container.database.session_factory()
    try:
        job = db.get(BlockchainAnchorJob, job_id)
        assert job.state == BlockchainAnchorJobState.CONFIRMED
        assert job.attempts == attempt_budget
        assert provider.reconcile_calls == 1
    finally:
        db.close()


def test_exhausted_unprepared_job_is_terminalized_after_a_crash(client):
    provider = _FakeEAS()
    service = _service(client, provider)
    job_id = service.enqueue(
        commitment_hash="bd" * 32,
        commitment_type=BlockchainCommitmentType.EVIDENCE_PACKET,
        subject_type="scan",
        subject_id="scan-exhausted-before-prepare",
        tenant_id=client.app.state.container.settings.dev_tenant_id,
    )
    db = client.app.state.container.database.session_factory()
    try:
        job = db.get(BlockchainAnchorJob, job_id)
        job.state = BlockchainAnchorJobState.RETRYABLE
        job.attempts = job.max_attempts
        db.commit()
    finally:
        db.close()

    assert service.process_job(job_id) is False

    db = client.app.state.container.database.session_factory()
    try:
        job = db.get(BlockchainAnchorJob, job_id)
        assert job.state == BlockchainAnchorJobState.FAILED
        assert job.last_error == "BLOCKCHAIN_ANCHOR_ATTEMPTS_EXHAUSTED"
        assert provider.anchor_calls == 0
        assert provider.reconcile_calls == 0
    finally:
        db.close()


@pytest.mark.parametrize(
    ("binding_mode", "expected_state", "expected_error"),
    [
        ("generic_only", BlockchainAnchorJobState.CONFIRMED, None),
        (
            "missing",
            BlockchainAnchorJobState.RETRYABLE,
            "RECEIPT_COMMITMENT_MISSING_OR_CONFLICTING",
        ),
        (
            "mismatch",
            BlockchainAnchorJobState.RETRYABLE,
            "RECEIPT_COMMITMENT_MISMATCH",
        ),
        (
            "conflicting",
            BlockchainAnchorJobState.RETRYABLE,
            "RECEIPT_COMMITMENT_MISSING_OR_CONFLICTING",
        ),
    ],
)
def test_packet_confirmation_requires_an_unambiguous_receipt_commitment(
    client, binding_mode, expected_state, expected_error
):
    class ReceiptBindingEAS(_FakeEAS):
        def anchor(self, commitment_hash, **kwargs):
            result = super().anchor(commitment_hash, **kwargs)
            detail = dict(result.receipt)
            if binding_mode == "generic_only":
                detail.pop("packet_hash_sha256", None)
            elif binding_mode == "missing":
                detail.pop("packet_hash_sha256", None)
                detail.pop("commitment_hash_sha256", None)
            elif binding_mode == "mismatch":
                detail["packet_hash_sha256"] = "00" * 32
                detail["commitment_hash_sha256"] = "00" * 32
            else:
                detail["packet_hash_sha256"] = "00" * 32
            return ProofReceipt(status=result.status, provider=result.provider, receipt=detail)

    service = _service(client, ReceiptBindingEAS())
    receipt = service.anchor_packet(
        packet_hash="be" * 32,
        scan_id=f"scan-binding-{binding_mode}",
        tenant_id=client.app.state.container.settings.dev_tenant_id,
    )

    db = client.app.state.container.database.session_factory()
    try:
        job = db.scalar(select(BlockchainAnchorJob))
        assert job.state == expected_state
        assert job.last_error == expected_error
        assert receipt.status == (
            AnchorStatus.ANCHORED
            if expected_state == BlockchainAnchorJobState.CONFIRMED
            else AnchorStatus.PENDING
        )
    finally:
        db.close()


def test_integrity_event_is_signed_logged_and_checkpoint_queued(client):
    provider = _FakeEAS()
    service = _service(client, provider)
    container = client.app.state.container
    db = container.database.session_factory()
    try:
        result = record_integrity_event(
            db,
            signer=container.signer,
            transparency=container.transparency,
            blockchain=service,
            tenant_id=container.settings.dev_tenant_id,
            event_type="WORK_REGISTERED",
            subject_type="work",
            subject_id="wrk_test",
            attributes={"sha256": "ab" * 32},
        )
        event = db.get(IntegrityEvent, result["event_id"])
        assert event.signature_b64
        assert result["transparency"]["inclusion_verified"] is True
        checkpoint_job = db.get(BlockchainAnchorJob, result["blockchain_anchor_job_id"])
        assert checkpoint_job.commitment_type == BlockchainCommitmentType.TRANSPARENCY_CHECKPOINT
    finally:
        db.close()


def test_trailing_partial_batch_is_checkpointed_after_max_age(client):
    container = client.app.state.container
    transparency = TransparencyLog(
        log_id="tail-flush-test",
        signer=container.signer,
        checkpoint_interval=3,
    )
    db = container.database.session_factory()
    try:
        receipt = transparency.append(db, packet_hash="cd" * 32, statement_id="stm_tail")
        assert receipt["checkpoint"] is None

        checkpoint = transparency.flush_due_checkpoint(
            db,
            max_age_seconds=60,
            now=datetime.now(UTC) + timedelta(seconds=61),
        )
        assert checkpoint is not None
        assert checkpoint["tree_size"] == 1
        assert checkpoint["root_sha256"] == receipt["root_sha256"]
        assert (
            transparency.flush_due_checkpoint(
                db,
                max_age_seconds=60,
                now=datetime.now(UTC) + timedelta(seconds=120),
            )
            is None
        )
    finally:
        db.close()


def test_confirmed_checkpoint_persists_portable_external_commitment(client):
    provider = _FakeEAS()
    service = _service(client, provider)
    container = client.app.state.container
    db = container.database.session_factory()
    try:
        receipt = container.transparency.append(
            db,
            packet_hash="de" * 32,
            statement_id="stm_portable",
        )
    finally:
        db.close()
    job_id = service.enqueue_checkpoint(receipt)

    assert job_id is not None
    assert service.process_job(job_id) is True

    db = container.database.session_factory()
    try:
        checkpoint = db.scalar(
            select(TransparencyCheckpoint).where(
                TransparencyCheckpoint.root_sha256 == receipt["checkpoint"]["root_sha256"]
            )
        )
        assert checkpoint.external_commitment["confirmation_state"] == "CONFIRMED"
        assert checkpoint.external_commitment["root_sha256"] == checkpoint.root_sha256
        assert checkpoint.external_commitment["protocol_finality_state"] == "NOT_VERIFIED"
        portable_receipt = checkpoint.external_commitment["receipt"]
        assert "finalized" not in portable_receipt
        assert "finality_reached" not in portable_receipt
        assert portable_receipt["anchor_conditions_met"] is True
    finally:
        db.close()


def _auditor_auth(container) -> AuthContext:
    return AuthContext(
        tenant_id=container.settings.dev_tenant_id,
        auth_method="test",
        role=PrincipalRole.AUDITOR,
        scopes=frozenset({CredentialScope.WORKS_READ}),
    )


def test_integrity_api_requires_exact_leaf_root_and_on_chain_receipt_binding(client):
    provider = _FakeEAS()
    service = _service(client, provider)
    container = client.app.state.container
    container.blockchain = service
    db = container.database.session_factory()
    try:
        recorded = record_integrity_event(
            db,
            signer=container.signer,
            transparency=container.transparency,
            blockchain=service,
            tenant_id=container.settings.dev_tenant_id,
            event_type="WORK_REGISTERED",
            subject_type="work",
            subject_id="wrk_integrity_binding",
            attributes={"sha256": "ef" * 32},
        )
    finally:
        db.close()
    assert service.process_job(recorded["blockchain_anchor_job_id"]) is True

    db = container.database.session_factory()
    try:
        payload = subject_integrity(
            "work",
            "wrk_integrity_binding",
            _auditor_auth(container),
            db,
            container,
        )
        event = payload["events"][0]
        assert event["public_chain"]["status"] == "CONFIRMED"
        assert event["public_chain"]["binding_verified"] is True
        assert all(event["public_chain"]["binding_checks"].values())
        assert event["public_chain_anchor"] is not None
    finally:
        db.close()


def test_integrity_api_never_exports_mismatched_confirmed_receipt_as_chain_proof(client):
    provider = _FakeEAS()
    service = _service(client, provider)
    container = client.app.state.container
    container.blockchain = service
    db = container.database.session_factory()
    try:
        recorded = record_integrity_event(
            db,
            signer=container.signer,
            transparency=container.transparency,
            blockchain=service,
            tenant_id=container.settings.dev_tenant_id,
            event_type="WORK_REGISTERED",
            subject_type="work",
            subject_id="wrk_bad_chain_binding",
            attributes={"sha256": "f0" * 32},
        )
    finally:
        db.close()
    job_id = recorded["blockchain_anchor_job_id"]
    assert service.process_job(job_id) is True

    db = container.database.system_session()
    try:
        job = db.get(BlockchainAnchorJob, job_id)
        envelope = dict(job.receipt)
        detail = dict(envelope["receipt"])
        detail["checkpoint_hash_sha256"] = "00" * 32
        detail["commitment_hash_sha256"] = "00" * 32
        envelope["receipt"] = detail
        job.receipt = envelope
        db.commit()
    finally:
        db.close()

    db = container.database.session_factory()
    try:
        payload = subject_integrity(
            "work",
            "wrk_bad_chain_binding",
            _auditor_auth(container),
            db,
            container,
        )
        event = payload["events"][0]
        assert event["public_chain"]["status"] == "VERIFICATION_FAILED"
        assert event["public_chain"]["binding_verified"] is False
        assert event["public_chain_anchor"] is None
    finally:
        db.close()


def test_strict_scan_completes_and_requeues_notify_only_after_confirmation(client):
    provider = _FakeEAS()
    service = _service(client, provider)
    service.settings = service.settings.model_copy(update={"proof_require_chain": True})
    container = client.app.state.container
    scan = Scan(
        id="scn_strict_confirmation",
        tenant_id=container.settings.dev_tenant_id,
        idempotency_key="strict-chain-confirmation",
        catalog_id="catalog",
        intended_use="test",
        candidate_sha256="ab" * 32,
        candidate_phash="00" * 8,
        state="COMPLETED",
        lifecycle_state=str(ScanLifecycleState.RESULT_READY),
        evidence_packet={"proof": {"packet_hash_sha256": "ab" * 32}},
    )
    db = container.database.session_factory()
    try:
        db.add(scan)
        db.commit()
    finally:
        db.close()

    receipt = service.anchor_packet(
        packet_hash="ab" * 32,
        scan_id=scan.id,
        tenant_id=scan.tenant_id,
    )
    assert receipt.status == AnchorStatus.ANCHORED

    db = container.database.session_factory()
    try:
        persisted = db.get(Scan, scan.id)
        assert persisted.lifecycle_state == str(ScanLifecycleState.COMPLETED)
        recovery = db.scalar(
            select(OutboxEvent).where(
                OutboxEvent.tenant_id == scan.tenant_id,
                OutboxEvent.payload["scan_id"].as_string() == scan.id,
            )
        )
        assert recovery is not None
        assert recovery.payload["reason"] == "PUBLIC_CHAIN_CONFIRMED"
    finally:
        db.close()


def test_evidence_statement_predecessor_has_at_most_one_successor(client):
    container = client.app.state.container
    db = container.database.session_factory()
    try:
        common = {
            "tenant_id": container.settings.dev_tenant_id,
            "scan_id": "scn_lineage_unique",
            "payload_digest_sha256": "12" * 32,
        }
        db.add(EvidenceStatement(id="stm_parent", **common))
        db.add(
            EvidenceStatement(
                id="stm_child_one",
                previous_statement_id="stm_parent",
                **common,
            )
        )
        db.commit()
        db.add(
            EvidenceStatement(
                id="stm_child_two",
                previous_statement_id="stm_parent",
                **common,
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
    finally:
        db.close()


def test_production_requires_real_signing_and_chain_trust_configuration():
    with pytest.raises(ValueError, match="(Unsafe production configuration|CHECKPOINT_SCHEMA_UID)"):
        Settings(
            environment="production",
            dev_auth_enabled=False,
            dev_api_key="not-a-published-default",
            api_key_pepper="private-deployment-pepper",
            database_url="postgresql://creatorproof@example.invalid/creatorproof",
            proof_anchor_mode="eas",
            proof_require_chain=True,
        )


def test_chain_requirement_cannot_silently_select_a_local_provider():
    with pytest.raises(ValueError, match="PROOF_ANCHOR_MODE=eas"):
        Settings(proof_anchor_mode="auto", proof_require_chain=True)


def test_required_chain_must_pin_the_network_and_the_attester():
    """ "Required" is meaningless if any RPC and any key would satisfy it."""
    with pytest.raises(ValueError, match="needs a pinned deployment"):
        Settings(
            proof_anchor_mode="eas",
            proof_require_chain=True,
            eas_rpc_url="https://rpc.invalid",
            eas_contract_address="0x" + "11" * 20,
            eas_schema_uid="0x" + "22" * 32,
            eas_checkpoint_schema_uid="0x" + "23" * 32,
            eas_private_key="0x" + "33" * 32,
        )


def test_production_counterparty_attestation_requires_its_schema_and_registry():
    with pytest.raises(ValueError, match="COATTESTATION_SCHEMA_UID|MEMBER_REGISTRY_ADDRESS"):
        Settings(
            environment="production",
            dev_auth_enabled=False,
            dev_api_key="not-a-published-default",
            api_key_pepper="private-deployment-pepper",
            database_url="postgresql://creatorproof@example.invalid/creatorproof",
            enable_postgres_rls=True,
            proof_anchor_mode="eas",
            proof_require_chain=True,
            statement_signing_private_key_hex="11" * 32,
            eas_rpc_url="https://rpc.invalid",
            eas_contract_address="0x" + "11" * 20,
            eas_schema_uid="0x" + "22" * 32,
            eas_checkpoint_schema_uid="0x" + "23" * 32,
            eas_private_key="0x" + "33" * 32,
            eas_chain_id=84532,
            eas_required_attester_address="0x" + "44" * 20,
            eas_expected_contract_code_sha256="55" * 32,
            eas_finality_policy="safe",
            eas_max_fee_per_gas_gwei=5.0,
            blockchain_counterparty_attestation_enabled=True,
        )


def test_eas_domain_anchoring_requires_a_separate_checkpoint_schema():
    with pytest.raises(ValueError, match="CHECKPOINT_SCHEMA_UID"):
        Settings(
            proof_anchor_mode="eas",
            eas_rpc_url="https://rpc.invalid",
            eas_contract_address="0x" + "11" * 20,
            eas_schema_uid="0x" + "22" * 32,
            eas_private_key="0x" + "33" * 32,
        )


def test_signing_settings_hide_private_material_from_repr():
    settings = Settings(
        dev_api_key="private-development-api-key",
        api_key_pepper="private-api-key-pepper",
        redis_url="redis://:private-password@redis.invalid:6379/0",
        statement_signing_private_key_hex="11" * 32,
        eas_private_key="0x" + "22" * 32,
        eas_rpc_url="https://secret-rpc.invalid/token",
    )
    rendered = repr(settings)
    assert "11" * 32 not in rendered
    assert "22" * 32 not in rendered
    assert "secret-rpc" not in rendered
    assert "private-development-api-key" not in rendered
    assert "private-api-key-pepper" not in rendered
    assert "private-password" not in rendered
