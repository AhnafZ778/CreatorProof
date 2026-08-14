import json
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.domain.enums import CopyRetrievalRequirement, OriginPolicyMode, RegistrationOriginGate

_INSECURE_DEV_KEYS = frozenset({"change-me-before-sharing", "creatorproof-dev-key"})


def _hex_bytes(value: str, *, setting: str, expected_length: int) -> bytes:
    normalized = value.strip()
    if normalized.lower().startswith("0x"):
        normalized = normalized[2:]
    if normalized.lower().startswith("sha256:"):
        normalized = normalized[7:]
    try:
        decoded = bytes.fromhex(normalized)
    except ValueError as exc:
        raise ValueError(f"{setting} must be hexadecimal") from exc
    if len(decoded) != expected_length:
        raise ValueError(f"{setting} must contain exactly {expected_length} bytes")
    return decoded


class Settings(BaseSettings):
    app_name: str = "CreatorProof API"
    environment: Literal["development", "test", "production"] = "development"
    database_url: str = "sqlite:///./creatorproof.db"
    storage_root: Path = Path("./data")
    job_backend: Literal["inline", "local", "redis"] = "local"
    local_job_workers: int = Field(default=1, ge=1, le=4)
    redis_url: str = Field(default="redis://localhost:6379/0", repr=False)
    redis_queue_name: str = "creatorproof:scans"
    redis_job_max_attempts: int = Field(default=3, ge=1, le=10)
    redis_job_lease_seconds: int = Field(default=1800, ge=60, le=7200)
    redis_job_recovery_interval_seconds: int = Field(default=30, ge=5, le=300)
    redis_job_claim_timeout_seconds: int = Field(default=5, ge=1, le=30)
    dev_api_key: str = Field(default="change-me-before-sharing", min_length=8, repr=False)
    dev_tenant_id: str = "tn_demo"
    dev_tenant_slug: str = "demo"

    # S11 durable orchestration. Redis Streams is the transport; PostgreSQL stays
    # authoritative, so a lost or duplicated stream message cannot change an outcome.
    redis_transport: Literal["list", "streams"] = "streams"
    redis_stream_name: str = "creatorproof:scans:stream"
    redis_consumer_group: str = "creatorproof-workers"
    redis_stream_maxlen: int = Field(default=10_000, ge=100)
    outbox_dispatch_interval_seconds: float = Field(default=1.0, ge=0.05, le=60.0)
    outbox_max_attempts: int = Field(default=8, ge=1, le=50)
    stage_lease_seconds: int = Field(default=180, ge=10, le=3600)
    stage_heartbeat_seconds: int = Field(default=15, ge=1, le=300)
    stage_max_attempts: int = Field(default=3, ge=1, le=10)
    stage_reaper_interval_seconds: float = Field(default=10.0, ge=1.0, le=300.0)
    scan_deadline_seconds: int = Field(default=900, ge=30, le=86_400)

    # S13 authentication and tenancy. `dev_auth_enabled` is refused in production so a
    # demo key can never be mistaken for a production credential boundary.
    api_key_pepper: str = Field(default="creatorproof-development-pepper", min_length=8, repr=False)
    dev_auth_enabled: bool = True
    enable_postgres_rls: bool = True
    rate_limit_requests_per_minute: int = Field(default=120, ge=1, le=100_000)
    rate_limit_burst: int = Field(default=40, ge=1, le=10_000)
    upload_concurrency_limit: int = Field(default=8, ge=1, le=256)
    tenant_scan_quota_per_day: int = Field(default=0, ge=0)

    # S12 evidence signing. The private key stays in the environment or a secret
    # manager; only the public key and key id are persisted.
    statement_signing_enabled: bool = True
    statement_signing_kid: str = "creatorproof-dev-ed25519-1"
    statement_signing_private_key_hex: str = Field(default="", repr=False)
    # Optional externally published pin. Verifiers must compare this fingerprint
    # against a value obtained outside the verification package; a key bundled in
    # the package is useful for self-consistency only and is not a trust root.
    trusted_issuer_key_sha256: str = ""
    transparency_log_id: str = "creatorproof-statements"
    transparency_checkpoint_interval: int = Field(default=1, ge=1, le=10_000)
    # A partial batch must not wait forever when traffic stops before the next
    # interval boundary. The blockchain dispatcher signs the current head after
    # this maximum delay and can then queue that checkpoint for public anchoring.
    transparency_checkpoint_max_age_seconds: float = Field(default=60.0, ge=1.0, le=86_400.0)

    # S16 webhooks. Deliveries are signed, timestamped and replay-bounded.
    webhook_timeout_seconds: int = Field(default=10, ge=1, le=120)
    webhook_max_attempts: int = Field(default=5, ge=1, le=20)
    webhook_replay_window_seconds: int = Field(default=300, ge=30, le=3600)
    webhook_allow_private_hosts: bool = False
    bulk_import_max_files: int = Field(default=50, ge=1, le=500)

    # S14 observability.
    log_format: Literal["json", "text"] = "json"
    metrics_enabled: bool = True
    max_upload_bytes: int = 12 * 1024 * 1024
    max_image_pixels: int = 40_000_000
    model_bundle_path: Path = Path("./model_lab/bundles/creatorproof-runtime-ready-v1.json")
    model_bundle_strict: bool = False
    runtime_lock_path: Path = Path("./uv.lock")
    retrieval_top_k: int = 8
    copy_regional_retrieval_enabled: bool = True
    copy_regional_crop_fraction: float = Field(default=0.64, ge=0.5, le=0.9)
    copy_regional_min_short_side: int = Field(default=192, ge=64, le=2048)
    copy_regional_similarity_penalty: float = Field(default=0.02, ge=0.0, le=0.2)
    copy_exhaustive_verification_max_entries: int = Field(default=64, ge=0, le=512)
    copy_retrieval_requirement: CopyRetrievalRequirement = CopyRetrievalRequirement.LEARNED_REQUIRED
    # Descriptor matching fails on two common kinds of honest reuse for reasons
    # unrelated to whether the images match: a horizontal flip, which costs a
    # reposter nothing and defeats a matcher outright, and flat or repetitive
    # work, where the ratio test discards every repeated element. When the
    # learned descriptor still puts a reference at or above this similarity but
    # the pixels refuse to align, alignment is retried against a mirror and then
    # under relaxed matching. Set to 1.0 to switch the extra passes off; the cost
    # is up to two more verifications per candidate this similar and unaligned.
    copy_alignment_escalation_similarity: float = Field(default=0.55, ge=0.0, le=1.0)
    candidate_retention_seconds: int = 0
    sscd_model_path: Path = Path("./models/sscd_disc_mixup.torchscript.pt")
    sscd_device: Literal["auto", "cpu", "cuda"] = "auto"
    sscd_expected_sha256: str = ""
    sscd_match_similarity: float = 0.75
    sscd_review_similarity: float = 0.60
    # v0.5 evidence-fusion operating points. These are intentionally exposed and
    # explicitly prototype-only until deployment-domain ROC/FPR calibration is run.
    copy_structure_match_similarity: float = 0.76
    copy_structure_very_strong_similarity: float = 0.84
    copy_geometry_very_strong_quality: float = 0.72
    copy_sscd_support_similarity: float = 0.55
    copy_geometry_sscd_match_similarity: float = 0.70
    copy_sscd_very_strong_similarity: float = 0.86
    copy_structure_support_similarity: float = 0.62
    copy_phash_support_similarity: float = 0.78
    # A small crop of a registered work is the case where the global descriptor
    # is least useful — it is looking at a different picture — and where aligned
    # pixels are most conclusive. When a strictly verified alignment has nearly
    # every match agreeing with it and the overlapping pixels are effectively
    # identical, that is a demonstration rather than a hypothesis, and it stands
    # without a retrieval-side second opinion.
    copy_conclusive_structure_similarity: float = Field(default=0.97, ge=0.0, le=1.0)
    copy_conclusive_inlier_ratio: float = Field(default=0.90, ge=0.0, le=1.0)
    copy_global_review_similarity: float = 0.80
    copy_phash_review_similarity: float = 0.90
    style_provider: Literal["auto", "csd", "diagnostic"] = "auto"
    style_csd_repo_path: Path = Path("./vendor/CSD")
    style_csd_model_path: Path = Path("./models/csd-vit-l/pytorch_model.bin")
    style_device: Literal["auto", "cpu", "cuda"] = "auto"
    style_top_k: int = 5
    # v0.6 CSD+ readout and corroborated style-evidence operating points. CSLS is
    # used for catalog ranking; the evidence thresholds remain prototype defaults
    # until a creator/domain-specific held-out calibration run supplies replacements.
    style_csls_k: int = 15
    style_learned_support_similarity: float = 0.68
    style_mechanics_support_similarity: float = 0.70
    style_tile_support_similarity: float = 0.68
    style_content_gap_support: float = 0.12
    style_catalog_margin_support: float = 0.03
    style_evidence_review_similarity: float = 0.58
    style_evidence_high_similarity: float = 0.74
    style_evidence_very_high_similarity: float = 0.84
    # PyTorch 2.6+ safely rejects some legacy pickle checkpoints. Unsafe pickle
    # loading stays opt-in and requires an expected SHA-256 supplied by the operator.
    style_allow_legacy_pickle: bool = False
    style_csd_expected_sha256: str = ""
    style_csd_expected_repo_revision: str = "3a9df32605b869eceb704897839be80977a9f1ea"
    style_profile_manifest_path: Path = Path("./model_lab/profiles/demo-profiles.v1.json")
    style_profile_manifest_strict: bool = False

    # v0.9 synthetic-origin evidence. Detection is deliberately independent from
    # copy and style evidence: a score can route a case to review but cannot prove
    # that an image is human-made, identify training data, or establish infringement.
    # With Sightengine credentials, ``auto`` and ``sightengine`` make its genai
    # endpoint the primary detector. Locally installed detectors are invoked only
    # if that primary request is unavailable or fails; they are not blended into a
    # healthy vendor result.
    synthetic_detector: Literal["auto", "sightengine", "community", "torchscript", "off"] = "auto"
    sightengine_api_user: str = Field(default="", repr=False)
    sightengine_api_secret: str = Field(default="", repr=False)
    sightengine_timeout_seconds: float = Field(default=20.0, ge=1.0, le=120.0)
    synthetic_community_model_path: Path = Path("./models/community-forensics-384")
    synthetic_community_expected_sha256: str = ""
    synthetic_torchscript_model_path: Path = Path("./models/synthetic-detector.torchscript.pt")
    synthetic_device: Literal["auto", "cpu", "cuda"] = "auto"
    synthetic_external_detectors_json: str = "[]"
    synthetic_evidence_family_registry_path: Path = Path(
        "./model_lab/registries/synthetic-evidence-families.v1.json"
    )
    synthetic_calibration_path: Path = Path("./models/synthetic-calibration.json")
    synthetic_calibration_domain_id: str = "creatorproof-demo-open-world-v1"
    synthetic_crop_policy_id: str = "creatorproof-origin-multiview-v3"
    synthetic_min_calibration_samples: int = 100
    synthetic_min_calibration_class_samples: int = 25
    synthetic_likely_threshold: float = 0.78
    synthetic_review_threshold: float = 0.58
    synthetic_max_view_std: float = 0.18
    synthetic_min_short_side: int = 128
    synthetic_spatial_crops: bool = True
    synthetic_spatial_crop_fraction: float = Field(default=0.78, ge=0.60, le=0.95)
    synthetic_min_independent_families: int = Field(default=2, ge=2, le=8)
    synthetic_external_timeout_seconds: int = Field(default=120, ge=5, le=600)
    synthetic_policy_mode: OriginPolicyMode = OriginPolicyMode.INFORMATIONAL

    # Enrollment gate. A protected-works catalog is a record of human authorship,
    # so the origin lane also runs when a work is registered and BLOCK refuses the
    # file once it reports AI indicators. It never refuses on an inconclusive or
    # unavailable result: those are the absence of a finding, and treating them as
    # one would lock real artists out of their own catalog.
    registration_origin_gate: RegistrationOriginGate = RegistrationOriginGate.BLOCK

    # How much AI signal refuses a registration. The gate is deliberately lenient
    # below this line: a weak or contested indicator is not enough to turn an
    # artist away from their own catalog, so only an ensemble score above it is
    # treated as a finding. Signed provenance that asserts AI generation refuses
    # regardless, because that is the file declaring its own origin rather than a
    # detector guessing at it.
    registration_origin_block_score: float = Field(default=0.50, ge=0.0, le=1.0)

    # Visible labels are a separate, forgeable review signal. They never count as
    # trusted provenance and their absence never counts as evidence of human origin.
    visible_ai_marker_mode: Literal["auto", "tesseract", "off"] = "auto"
    visible_ai_marker_binary: str = "tesseract"
    visible_ai_marker_timeout_seconds: int = Field(default=12, ge=1, le=120)
    visible_ai_marker_min_confidence: float = Field(default=0.42, ge=0.0, le=1.0)
    visible_ai_marker_terms_json: str = "[]"

    # C2PA is evaluated as provenance, not as a truth/fake classifier. The CLI
    # adapter uses the official c2patool binary and never shells through a command
    # interpreter. A missing manifest is UNKNOWN origin, not evidence of a human source.
    c2pa_mode: Literal["auto", "off"] = "auto"
    c2pa_binary: str = "c2patool"
    c2pa_expected_version: str = "0.27.7"
    c2pa_expected_binary_sha256: str = (
        "cceb21184cf0f5f3e4dce38275a225ad8ea50d2cda559df7a90ca0737248ad70"
    )
    c2pa_timeout_seconds: int = 20
    c2pa_trust_policy_id: str = "creatorproof-c2patool-default-trust-evaluation-v1"

    # Proof anchoring has two explicit levels. The local Merkle log is an auditable
    # transparency receipt, not a blockchain. EAS mode submits only a bytes32 packet
    # commitment to a configured EVM network and returns the mined transaction receipt.
    proof_anchor_mode: Literal["auto", "none", "merkle", "eas"] = "auto"
    proof_log_path: Path = Path("./data/proof-log.jsonl")
    eas_rpc_url: str = Field(default="", repr=False)
    # Ordered failover RPC endpoints. The legacy single URL remains supported and
    # is prepended when it is not already present in this JSON array.
    eas_rpc_urls_json: str = Field(default="[]", repr=False)
    eas_contract_address: str = ""
    eas_schema_uid: str = ""
    eas_checkpoint_schema_uid: str = ""
    eas_coattestation_schema_uid: str = ""
    eas_schema_registry_address: str = ""
    eas_schema_definition: str = "bytes32 packetHash"
    eas_checkpoint_schema_definition: str = "bytes32 checkpointHash"
    eas_coattestation_schema_definition: str = "bytes32 coAttestationHash"
    eas_expected_contract_code_sha256: str = ""
    eas_required_attester_address: str = ""
    eas_private_key: str = Field(default="", repr=False)
    eas_recipient: str = "0x0000000000000000000000000000000000000000"
    eas_explorer_tx_base_url: str = ""
    eas_chain_id: int | None = None
    eas_receipt_timeout_seconds: int = 90
    # S7 competition-demo hardening. `eas_network_label` and the explorer bases are
    # display metadata; `eas_required_confirmations` and the retry budget make an
    # intermittent public testnet survivable without ever blocking scan completion.
    eas_network_label: str = ""
    eas_explorer_address_base_url: str = ""
    eas_explorer_attestation_base_url: str = ""
    eas_required_confirmations: int = Field(default=1, ge=0, le=64)
    # `confirmation_depth` is a compatibility policy for development networks.
    # `safe`/`finalized` require the corresponding JSON-RPC block tag to cover
    # the attestation block and are mandatory choices in production.
    eas_finality_policy: Literal["confirmation_depth", "safe", "finalized"] = "confirmation_depth"
    eas_max_attempts: int = Field(default=3, ge=1, le=10)
    eas_retry_backoff_seconds: float = Field(default=3.0, ge=0.0, le=120.0)
    eas_max_fee_per_gas_gwei: float = Field(default=0.0, ge=0.0)
    # When true a configured chain anchor that fails is reported as FAILED instead of
    # silently degrading to a local receipt. The evidence result is never changed.
    proof_require_chain: bool = False
    # Domain events with lasting evidentiary value (registrations, rights-state
    # changes, status statements) enter the signed local transparency tree. Rather
    # than spending one transaction per row, completed checkpoint roots are queued
    # for EAS anchoring. Set the checkpoint interval to 1 for a competition demo and
    # a larger value in production for batching.
    blockchain_domain_anchoring_enabled: bool = True
    blockchain_dispatch_interval_seconds: float = Field(default=2.0, ge=0.1, le=300.0)
    blockchain_anchor_lease_seconds: int = Field(default=180, ge=10, le=3600)
    blockchain_anchor_max_attempts: int = Field(default=8, ge=1, le=50)
    blockchain_anchor_retry_backoff_seconds: float = Field(default=5.0, ge=0.0, le=3600.0)

    # Multi-party attestation. A counterparty signs an EIP-712 payload with its own
    # EVM key; CreatorProof verifies the recovered address against the membership
    # registry and commits only the 32-byte body hash, bound to the platform
    # attestation through EAS refUID. Party identity stays off-chain.
    blockchain_counterparty_attestation_enabled: bool = True
    # The registry contract is also the EIP-712 verifying contract, so a signature
    # collected for one deployment cannot be replayed against another.
    eas_member_registry_address: str = ""
    eas_clearance_receipt_address: str = ""
    counterparty_attestation_domain_name: str = "CreatorProofNetwork"
    counterparty_attestation_domain_version: str = "1"
    # Bounds how long a collected signature stays presentable, limiting the window
    # in which a leaked counterparty signature can be submitted by someone else.
    counterparty_attestation_max_age_seconds: int = Field(default=900, ge=60, le=86_400)
    # When true an unknown or non-ACTIVE address is refused even if the on-chain
    # registry is unreachable. Only relax this on a development network.
    counterparty_membership_required: bool = True

    # Catalog-relative style calibration. High/very-high tiers require enough
    # within-creator positives and cross-creator negatives; otherwise the lane is
    # visibly restricted to a review candidate.
    style_min_profile_works: int = 3
    style_min_calibration_profiles: int = 3
    style_min_calibration_negatives: int = 19
    style_high_max_negative_tail_p: float = 0.10
    style_very_high_max_negative_tail_p: float = 0.05
    style_high_min_positive_percentile: float = 0.25
    style_very_high_min_positive_percentile: float = 0.50

    model_config = SettingsConfigDict(
        env_prefix="CREATORPROOF_",
        env_file=".env",
        extra="ignore",
    )

    @model_validator(mode="after")
    def _refuse_development_credentials_in_production(self) -> "Settings":
        """Fail startup rather than serve production traffic behind demo credentials."""
        try:
            rpc_urls = json.loads(self.eas_rpc_urls_json)
        except json.JSONDecodeError as exc:
            raise ValueError("CREATORPROOF_EAS_RPC_URLS_JSON must be valid JSON") from exc
        if not isinstance(rpc_urls, list) or any(
            not isinstance(url, str) or not url.strip() for url in rpc_urls
        ):
            raise ValueError("CREATORPROOF_EAS_RPC_URLS_JSON must be a JSON array of URLs")
        if self.trusted_issuer_key_sha256:
            _hex_bytes(
                self.trusted_issuer_key_sha256,
                setting="CREATORPROOF_TRUSTED_ISSUER_KEY_SHA256",
                expected_length=32,
            )
        if self.statement_signing_private_key_hex:
            _hex_bytes(
                self.statement_signing_private_key_hex,
                setting="CREATORPROOF_STATEMENT_SIGNING_PRIVATE_KEY_HEX",
                expected_length=32,
            )
        for setting, value in (
            ("CREATORPROOF_EAS_PRIVATE_KEY", self.eas_private_key),
            ("CREATORPROOF_EAS_SCHEMA_UID", self.eas_schema_uid),
            ("CREATORPROOF_EAS_CHECKPOINT_SCHEMA_UID", self.eas_checkpoint_schema_uid),
            ("CREATORPROOF_EAS_COATTESTATION_SCHEMA_UID", self.eas_coattestation_schema_uid),
            (
                "CREATORPROOF_EAS_EXPECTED_CONTRACT_CODE_SHA256",
                self.eas_expected_contract_code_sha256,
            ),
        ):
            if value:
                _hex_bytes(value, setting=setting, expected_length=32)
        if self.proof_require_chain and self.proof_anchor_mode != "eas":
            raise ValueError(
                "CREATORPROOF_PROOF_REQUIRE_CHAIN requires CREATORPROOF_PROOF_ANCHOR_MODE=eas"
            )
        # ``auto`` selects EAS once all constructor inputs are present. Treat that
        # state exactly like explicit EAS for invariants that must hold before the
        # first domain checkpoint can be queued.
        eas_constructor_complete = all(
            (
                self.eas_rpc_url or rpc_urls,
                self.eas_contract_address,
                self.eas_schema_uid,
                self.eas_private_key,
                self.eas_recipient,
            )
        )
        eas_may_activate = self.proof_anchor_mode == "eas" or (
            self.proof_anchor_mode == "auto" and eas_constructor_complete
        )
        if eas_may_activate and not self.statement_signing_enabled:
            raise ValueError(
                "CREATORPROOF_STATEMENT_SIGNING_ENABLED must be true when EAS may activate"
            )
        if self.blockchain_domain_anchoring_enabled and eas_may_activate:
            if not self.eas_checkpoint_schema_uid:
                raise ValueError(
                    "CREATORPROOF_EAS_CHECKPOINT_SCHEMA_UID is required when EAS domain "
                    "checkpoint anchoring is enabled"
                )
        # A deployment that forbids local fallback must also pin what it is
        # anchoring to. Without these two values "the chain is required" degrades
        # into "some chain the RPC happens to serve, signed by some key".
        if self.proof_require_chain:
            unpinned = [
                name
                for name, value in (
                    ("CREATORPROOF_EAS_CHAIN_ID", self.eas_chain_id),
                    (
                        "CREATORPROOF_EAS_REQUIRED_ATTESTER_ADDRESS",
                        self.eas_required_attester_address,
                    ),
                )
                if not value
            ]
            if unpinned:
                raise ValueError(
                    "CREATORPROOF_PROOF_REQUIRE_CHAIN needs a pinned deployment: "
                    + ", ".join(unpinned)
                )
        if self.environment != "production":
            return self
        problems: list[str] = []
        if self.dev_auth_enabled:
            problems.append("CREATORPROOF_DEV_AUTH_ENABLED must be false in production")
        if self.dev_api_key in _INSECURE_DEV_KEYS:
            problems.append("CREATORPROOF_DEV_API_KEY is still the published development value")
        if self.api_key_pepper == "creatorproof-development-pepper":
            problems.append("CREATORPROOF_API_KEY_PEPPER must be set to a private value")
        if not self.statement_signing_enabled:
            problems.append("CREATORPROOF_STATEMENT_SIGNING_ENABLED must be true in production")
        elif not self.statement_signing_private_key_hex:
            problems.append(
                "CREATORPROOF_STATEMENT_SIGNING_PRIVATE_KEY_HEX must contain a real, "
                "operator-managed Ed25519 seed"
            )
        if not self.trusted_issuer_key_sha256:
            problems.append("CREATORPROOF_TRUSTED_ISSUER_KEY_SHA256 must be published and pinned")
        if not self.enable_postgres_rls:
            problems.append("CREATORPROOF_ENABLE_POSTGRES_RLS must be true in production")
        if not self.database_url.startswith("postgresql"):
            problems.append("SQLite is a development convenience; production requires PostgreSQL")
        if self.proof_anchor_mode == "auto":
            problems.append(
                "CREATORPROOF_PROOF_ANCHOR_MODE must be explicit in production; "
                "auto can change trust semantics when credentials appear"
            )
        if self.proof_anchor_mode == "eas":
            missing = [
                name
                for name, value in (
                    ("CREATORPROOF_EAS_RPC_URL", self.eas_rpc_url or rpc_urls),
                    ("CREATORPROOF_EAS_CONTRACT_ADDRESS", self.eas_contract_address),
                    ("CREATORPROOF_EAS_SCHEMA_UID", self.eas_schema_uid),
                    ("CREATORPROOF_EAS_PRIVATE_KEY", self.eas_private_key),
                    (
                        "CREATORPROOF_EAS_EXPECTED_CONTRACT_CODE_SHA256",
                        self.eas_expected_contract_code_sha256,
                    ),
                )
                if not value
            ]
            if missing:
                problems.append(
                    "chain anchoring is required but configuration is missing: "
                    + ", ".join(missing)
                )
            if not self.eas_chain_id:
                problems.append(
                    "CREATORPROOF_EAS_CHAIN_ID must be pinned when chain anchoring is required"
                )
            if not self.eas_required_attester_address:
                problems.append(
                    "CREATORPROOF_EAS_REQUIRED_ATTESTER_ADDRESS must be pinned when "
                    "chain anchoring is required"
                )
            if self.blockchain_domain_anchoring_enabled and not self.eas_checkpoint_schema_uid:
                problems.append(
                    "CREATORPROOF_EAS_CHECKPOINT_SCHEMA_UID must be pinned when domain "
                    "checkpoint anchoring is enabled"
                )
            if self.eas_schema_definition.strip() != "bytes32 packetHash":
                problems.append(
                    "CREATORPROOF_EAS_SCHEMA_DEFINITION must be exactly 'bytes32 packetHash'"
                )
            if (
                self.blockchain_domain_anchoring_enabled
                and self.eas_checkpoint_schema_definition.strip() != "bytes32 checkpointHash"
            ):
                problems.append(
                    "CREATORPROOF_EAS_CHECKPOINT_SCHEMA_DEFINITION must be exactly "
                    "'bytes32 checkpointHash'"
                )
            if self.blockchain_counterparty_attestation_enabled:
                # An advertised multi-party capability that cannot actually write
                # a counterparty commitment is worse than one that is switched off.
                if not self.eas_coattestation_schema_uid:
                    problems.append(
                        "CREATORPROOF_EAS_COATTESTATION_SCHEMA_UID must be pinned when "
                        "counterparty attestation is enabled"
                    )
                if not self.eas_member_registry_address:
                    problems.append(
                        "CREATORPROOF_EAS_MEMBER_REGISTRY_ADDRESS must be pinned when "
                        "counterparty attestation is enabled; it is also the EIP-712 "
                        "verifying contract that binds a signature to this deployment"
                    )
                if self.eas_coattestation_schema_definition.strip() != "bytes32 coAttestationHash":
                    problems.append(
                        "CREATORPROOF_EAS_COATTESTATION_SCHEMA_DEFINITION must be exactly "
                        "'bytes32 coAttestationHash'"
                    )
                if not self.counterparty_membership_required:
                    problems.append(
                        "CREATORPROOF_COUNTERPARTY_MEMBERSHIP_REQUIRED must be true in production"
                    )
            if self.eas_finality_policy == "confirmation_depth":
                problems.append(
                    "CREATORPROOF_EAS_FINALITY_POLICY must be safe or finalized in production"
                )
            if self.eas_max_fee_per_gas_gwei <= 0:
                problems.append(
                    "CREATORPROOF_EAS_MAX_FEE_PER_GAS_GWEI must set a positive spending cap"
                )
        if problems:
            raise ValueError("Unsafe production configuration: " + "; ".join(problems))
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
