from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.domain.enums import AnchorStatus
from app.providers.proof import EASProofAnchor

PACKET_HASH = "aa" * 32
OTHER_HASH = "bb" * 32
UID = bytes.fromhex("11" * 32)
SCHEMA_UID = "0x" + ("22" * 32)
CHECKPOINT_SCHEMA_UID = "0x" + ("23" * 32)
COATTESTATION_SCHEMA_UID = "0x" + ("24" * 32)
PLATFORM_UID = "0x" + ("31" * 32)
CONTRACT = "0x" + ("33" * 20)
REGISTRY = "0x" + ("34" * 20)
MEMBER_REGISTRY = "0x" + ("35" * 20)
ATTESTER = "0x" + ("44" * 20)
RECIPIENT = "0x" + ("55" * 20)
CHAIN_ID = 84532


class _Web3Adapter:
    @staticmethod
    def is_address(value):
        return isinstance(value, str) and value.startswith("0x") and len(value) == 42

    @staticmethod
    def to_checksum_address(value):
        return value


class _Call:
    def __init__(self, value):
        self.value = value

    def call(self):
        return self.value


class _AttestationFunctions:
    def __init__(self, record, contract_valid=True):
        self.record = record
        self.contract_valid = contract_valid

    def getAttestation(self, _uid):
        return _Call(self.record)

    def isAttestationValid(self, _uid):
        return _Call(self.contract_valid)


class _Contract:
    def __init__(self, record, contract_valid=True):
        self.functions = _AttestationFunctions(record, contract_valid)


class _VerifyEth:
    def __init__(self, chain_id=CHAIN_ID, chain_time=1_000):
        self.chain_id = chain_id
        self.chain_time = chain_time

    def get_block(self, _block):
        return {"timestamp": self.chain_time}


class _VerifyWeb3:
    def __init__(self, chain_id=CHAIN_ID, chain_time=1_000):
        self.eth = _VerifyEth(chain_id, chain_time)

    def is_connected(self):
        return True


def _anchor(
    *,
    required_confirmations=1,
    checkpoint=False,
    coattestation=False,
    finality_policy="confirmation_depth",
):
    """Build a provider without importing optional web3 packages in unit tests."""
    anchor = object.__new__(EASProofAnchor)
    anchor.rpc_urls = ("https://rpc.invalid",)
    anchor.rpc_url = anchor.rpc_urls[0]
    anchor.contract_address = CONTRACT
    anchor.schema_uid = SCHEMA_UID
    anchor.private_key = "test-only"
    anchor.recipient = RECIPIENT
    anchor.schema_registry_address = REGISTRY
    anchor.schema_definition = "bytes32 packetHash"
    anchor.checkpoint_schema_uid = CHECKPOINT_SCHEMA_UID if checkpoint else ""
    anchor.checkpoint_schema_definition = "bytes32 checkpointHash"
    anchor.coattestation_schema_uid = COATTESTATION_SCHEMA_UID if coattestation else ""
    anchor.coattestation_schema_definition = "bytes32 coAttestationHash"
    anchor.member_registry_address = MEMBER_REGISTRY
    anchor.expected_contract_code_sha256 = ""
    anchor.required_attester_address = ATTESTER
    anchor.explorer_tx_base_url = ""
    anchor.explorer_address_base_url = ""
    anchor.explorer_attestation_base_url = ""
    anchor.chain_id = CHAIN_ID
    anchor.timeout_seconds = 0
    anchor.network_label = "base-sepolia"
    anchor.required_confirmations = required_confirmations
    anchor.finality_policy = finality_policy
    anchor.max_attempts = 1
    anchor.retry_backoff_seconds = 0
    anchor.max_fee_per_gas_wei = 0
    anchor.available = True
    anchor.unavailable_reason = None
    anchor._web3 = _Web3Adapter
    anchor.attester_address = ATTESTER
    return anchor


def _record(**overrides):
    values = {
        "uid": UID,
        "schema": bytes.fromhex(SCHEMA_UID.removeprefix("0x")),
        "time": 900,
        "expiration": 0,
        "revocation": 0,
        "ref_uid": bytes(32),
        "recipient": RECIPIENT,
        "attester": ATTESTER,
        "revocable": True,
        "data": bytes.fromhex(PACKET_HASH),
    }
    values.update(overrides)
    return (
        values["uid"],
        values["schema"],
        values["time"],
        values["expiration"],
        values["revocation"],
        values["ref_uid"],
        values["recipient"],
        values["attester"],
        values["revocable"],
        values["data"],
    )


def _verify(anchor, record, *, expected_hash=PACKET_HASH, metadata=None):
    web3 = _VerifyWeb3()
    contract = _Contract(record)
    anchor._connect = lambda: web3
    anchor._environment_status = lambda _web3: {"ready": True, "reason": None}
    anchor._contract = lambda _web3: contract
    return anchor.verify(
        attestation_uid="0x" + UID.hex(),
        expected_packet_hash=expected_hash,
        expected_metadata=metadata,
    )


def test_verify_binds_full_attestation_to_expected_packet():
    result = _verify(_anchor(), _record())

    assert result["checked"] is True
    assert result["attestation_valid"] is True
    assert result["packet_hash_sha256"] == PACKET_HASH
    assert all(value is not False for value in result["checks"].values())


@pytest.mark.parametrize(
    ("record_overrides", "reason_code"),
    [
        ({"data": bytes.fromhex(OTHER_HASH)}, "COMMITMENT_MATCHES_EXPECTED"),
        ({"data": b"short"}, "COMMITMENT_DECODES_AS_BYTES32"),
        ({"schema": bytes.fromhex("66" * 32)}, "SCHEMA_MATCHES_EXPECTED"),
        ({"attester": "0x" + ("77" * 20)}, "ATTESTER_MATCHES_EXPECTED"),
        ({"recipient": "0x" + ("88" * 20)}, "RECIPIENT_MATCHES_EXPECTED"),
        ({"revocation": 950}, "NOT_REVOKED"),
        ({"expiration": 999}, "NOT_EXPIRED"),
    ],
)
def test_verify_rejects_unrelated_or_mutated_valid_attestation(record_overrides, reason_code):
    # The contract-level validity flag remains true. Application-level field binding
    # must still reject an unrelated UID, wrong schema/signer/recipient, or stale state.
    result = _verify(_anchor(), _record(**record_overrides))

    assert result["attestation_valid"] is False
    assert reason_code in result["reason_codes"]


def test_uid_only_verification_is_compatible_but_marks_hash_comparison_unknown():
    anchor = _anchor()
    web3 = _VerifyWeb3()
    anchor._connect = lambda: web3
    anchor._environment_status = lambda _web3: {"ready": True, "reason": None}
    anchor._contract = lambda _web3: _Contract(_record())

    result = anchor.verify(attestation_uid="0x" + UID.hex())

    assert result["attestation_valid"] is True
    assert result["checks"]["commitment_matches_expected"] is None
    assert result["packet_hash_sha256"] == PACKET_HASH


def test_checkpoint_commitment_uses_separate_schema_and_non_revocable_policy():
    anchor = _anchor(checkpoint=True)
    record = _record(
        schema=bytes.fromhex(CHECKPOINT_SCHEMA_UID.removeprefix("0x")),
        revocable=False,
    )

    result = _verify(
        anchor,
        record,
        metadata={"commitment_type": "TRANSPARENCY_CHECKPOINT"},
    )

    assert result["attestation_valid"] is True
    assert result["commitment_type"] == "TRANSPARENCY_CHECKPOINT"
    assert result["checkpoint_hash_sha256"] == PACKET_HASH
    assert result["checks"]["revocability_matches_expected"] is True


def _coattestation_record(ref_uid: str = PLATFORM_UID):
    return _record(
        schema=bytes.fromhex(COATTESTATION_SCHEMA_UID.removeprefix("0x")),
        ref_uid=bytes.fromhex(ref_uid.removeprefix("0x")),
    )


def test_coattestation_verification_requires_the_platform_attestation_reference():
    """The two attestations are only provably related through refUID."""
    result = _verify(
        _anchor(coattestation=True),
        _coattestation_record(),
        metadata={
            "commitment_type": "COUNTERPARTY_ATTESTATION",
            "ref_uid": PLATFORM_UID,
        },
    )

    assert result["attestation_valid"] is True
    assert result["commitment_type"] == "COUNTERPARTY_ATTESTATION"
    assert result["coattestation_hash_sha256"] == PACKET_HASH
    assert result["checks"]["ref_uid_matches_expected"] is True


def test_coattestation_pointing_at_another_packet_attestation_is_rejected():
    result = _verify(
        _anchor(coattestation=True),
        _coattestation_record(ref_uid="0x" + "32" * 32),
        metadata={
            "commitment_type": "COUNTERPARTY_ATTESTATION",
            "ref_uid": PLATFORM_UID,
        },
    )

    assert result["attestation_valid"] is False
    assert "REF_UID_MATCHES_EXPECTED" in result["reason_codes"]


def test_coattestation_verification_rejects_the_platform_packet_schema():
    """A packet attestation must never read back as a counterparty commitment."""
    result = _verify(
        _anchor(coattestation=True),
        _record(ref_uid=bytes.fromhex(PLATFORM_UID.removeprefix("0x"))),
        metadata={
            "commitment_type": "COUNTERPARTY_ATTESTATION",
            "ref_uid": PLATFORM_UID,
        },
    )

    assert result["attestation_valid"] is False
    assert "SCHEMA_MATCHES_EXPECTED" in result["reason_codes"]


class _EnvironmentEth:
    def __init__(self, *, chain_id, code):
        self.chain_id = chain_id
        self.code = code

    def get_code(self, _address):
        return self.code


class _EnvironmentWeb3:
    def __init__(self, *, chain_id=CHAIN_ID, code=b"\x60\x00"):
        self.eth = _EnvironmentEth(chain_id=chain_id, code=code)

    def is_connected(self):
        return True


def test_preflight_rejects_rpc_on_wrong_chain():
    anchor = _anchor()
    anchor._connect = lambda: _EnvironmentWeb3(chain_id=1)

    result = anchor.preflight()

    assert result["ready"] is False
    assert result["reason"] == "EAS_CHAIN_ID_MISMATCH"


def test_preflight_rejects_eoa_or_fake_contract_with_no_bytecode():
    anchor = _anchor()
    anchor._connect = lambda: _EnvironmentWeb3(code=b"")

    result = anchor.preflight()

    assert result["ready"] is False
    assert result["reason"] == "EAS_CONTRACT_HAS_NO_CODE"


@pytest.mark.parametrize("finality_policy", ["safe", "finalized"])
def test_preflight_fails_closed_when_configured_finality_tag_is_unavailable(finality_policy):
    anchor = _anchor(finality_policy=finality_policy)
    requests = 0

    class Eth:
        @staticmethod
        def get_block(tag):
            nonlocal requests
            requests += 1
            assert tag == finality_policy
            raise RuntimeError("unsupported block tag")

    web3 = SimpleNamespace(eth=Eth())
    anchor._connect = lambda: web3
    anchor._environment_status = lambda _web3: {"ready": True, "reason": None}

    status = anchor.status()
    result = anchor._last_preflight
    cached_status = anchor.status()

    assert result is not None
    assert result["ready"] is False
    assert result["configured_finality_tag"] == finality_policy
    assert result["finality_tag_supported"] is False
    assert result["reason"] == f"EAS_{finality_policy.upper()}_BLOCK_TAG_UNAVAILABLE"
    assert status["configured"] is True
    assert status["live_write_ready"] is False
    assert status["live_write_reason"] == result["reason"]
    assert status["live_write_checked_at"] == result["checked_at"]
    assert cached_status["live_write_checked_at"] == result["checked_at"]
    assert requests == 1


@pytest.mark.parametrize("finality_policy", ["safe", "finalized"])
def test_preflight_probes_and_reports_the_configured_finality_tag(finality_policy):
    anchor = _anchor(finality_policy=finality_policy)
    requested_tags = []

    class Eth:
        @staticmethod
        def get_block(tag):
            requested_tags.append(tag)
            return {"number": 123}

        @staticmethod
        def get_balance(_address):
            return 1

    web3 = SimpleNamespace(eth=Eth())
    anchor._connect = lambda: web3
    anchor._environment_status = lambda _web3: {"ready": True, "reason": None}
    anchor._fee_fields = lambda _web3: ({"gasPrice": 1}, 1)

    result = anchor.preflight()

    assert result["ready"] is True
    assert result["finality_tag_supported"] is True
    assert result["finality_tag_block_number"] == 123
    assert requested_tags == [finality_policy]
    assert anchor.status()["live_write_ready"] is True


@pytest.mark.parametrize(
    (
        "required_confirmations",
        "confirmations",
        "confirmation_depth_reached",
        "expected",
    ),
    [
        (2, 0, False, AnchorStatus.PENDING),
        (0, 0, True, AnchorStatus.ANCHORED),
    ],
)
def test_anchor_requires_configured_confirmation_depth(
    required_confirmations, confirmations, confirmation_depth_reached, expected
):
    anchor = _anchor(required_confirmations=required_confirmations)
    anchor._submit_once = lambda *_args, **_kwargs: {
        "transaction_status": 1,
        "attestation_valid": True,
        "canonical_receipt": True,
        "confirmations": confirmations,
        "confirmation_depth_reached": confirmation_depth_reached,
    }

    result = anchor.anchor(PACKET_HASH)

    assert result.status == expected


@pytest.mark.parametrize(
    ("finality_policy", "safe_verified", "finalized_verified", "expected"),
    [
        ("safe", False, False, AnchorStatus.PENDING),
        ("safe", True, False, AnchorStatus.ANCHORED),
        ("finalized", True, False, AnchorStatus.PENDING),
        ("finalized", True, True, AnchorStatus.ANCHORED),
    ],
)
def test_anchor_waits_for_selected_rpc_finality_policy(
    finality_policy, safe_verified, finalized_verified, expected
):
    anchor = _anchor(finality_policy=finality_policy)
    anchor._submit_once = lambda *_args, **_kwargs: {
        "transaction_status": 1,
        "attestation_valid": True,
        "canonical_receipt": True,
        "confirmations": 2,
        "confirmation_depth_reached": True,
        "safe_block_verified": safe_verified,
        "finalized_block_verified": finalized_verified,
    }

    result = anchor.anchor(PACKET_HASH)

    assert result.status == expected
    assert result.receipt["anchor_conditions_met"] is (expected == AnchorStatus.ANCHORED)
    assert result.receipt["finalized"] is (finalized_verified and expected == AnchorStatus.ANCHORED)


def test_confirmation_recheck_detects_noncanonical_block_hash():
    anchor = _anchor(required_confirmations=1)
    original = "0x" + ("90" * 32)
    replacement = "0x" + ("91" * 32)
    tx_hash = "0x" + ("92" * 32)
    mined = {"blockHash": original, "blockNumber": 50}

    class Eth:
        block_number = 50

        @staticmethod
        def get_transaction_receipt(_tx_hash):
            return {
                "blockHash": original,
                "blockNumber": 50,
                "status": 1,
                "transactionHash": tx_hash,
            }

        @staticmethod
        def get_block(_block):
            return {"hash": replacement}

        @staticmethod
        def get_transaction(_tx_hash):
            return {
                "hash": tx_hash,
                "to": CONTRACT,
                "from": ATTESTER,
            }

    result = anchor._confirmation_status(SimpleNamespace(eth=Eth()), mined, tx_hash)

    assert result["confirmations"] == 1
    assert result["confirmation_depth_reached"] is True
    assert result["finalized_block_verified"] is None
    assert result["canonical_receipt"] is False


def test_prepared_callback_runs_before_broadcast_and_can_abort_it():
    anchor = _anchor()
    EASProofAnchor._prepared_transactions.clear()
    tx_hash = bytes.fromhex("93" * 32)

    class Signed:
        raw_transaction = b"\x02signed-transaction"
        hash = tx_hash

    class Account:
        address = ATTESTER

        @staticmethod
        def sign_transaction(_transaction):
            return Signed()

    class AccountFactory:
        @staticmethod
        def from_key(_key):
            return Account()

    class AttestCall:
        @staticmethod
        def build_transaction(transaction):
            return transaction

    class Functions:
        @staticmethod
        def attest(_request):
            return AttestCall()

    class Contract:
        functions = Functions()

    class Eth:
        account = AccountFactory()
        chain_id = CHAIN_ID
        sends = 0

        @staticmethod
        def get_transaction_count(_address, _state):
            return 7

        @staticmethod
        def estimate_gas(_transaction):
            return 100_000

        @classmethod
        def send_raw_transaction(cls, _raw):
            cls.sends += 1
            return tx_hash

    web3 = SimpleNamespace(eth=Eth())
    anchor._contract = lambda _web3: Contract()
    anchor._environment_status = lambda _web3: {"ready": True, "reason": None}
    anchor._fee_fields = lambda _web3: ({"gasPrice": 1}, 1)

    captured = {}

    def abort(payload):
        captured.update(payload)
        raise RuntimeError("persist failed")

    with pytest.raises(RuntimeError, match="persist failed"):
        anchor._prepare_and_broadcast(
            web3,
            packet_hash=PACKET_HASH,
            commitment_type="EVIDENCE_PACKET",
            context={"scan_id": "sc_test"},
            on_transaction_prepared=abort,
            notify_callback=True,
        )

    assert captured["tx_hash"] == "0x" + tx_hash.hex()
    assert captured["nonce"] == 7
    assert captured["chain_id"] == CHAIN_ID
    assert captured["signed_transaction_hex"].startswith("0x02")
    assert Eth.sends == 0
