from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
)
from sqlalchemy import (
    inspect as sa_inspect,
)
from sqlalchemy.orm import Mapped, mapped_column, object_session

from app.db import Base
from app.domain.enums import AnchorStatus, ClaimState, RightsPath, ScanState
from app.domain.platform import (
    BlockchainAnchorJobState,
    BlockchainCommitmentType,
    CounterpartyAttestationState,
    CounterpartyDecision,
    DeletionReceiptState,
    LicenseState,
    NetworkMemberRole,
    NetworkMemberStatus,
    OutboxState,
    PartyVerificationState,
    PrincipalRole,
    ReviewCaseState,
    ReviewDisposition,
    ScanLifecycleState,
    StageState,
    StatementStatus,
    StatementType,
    WebhookDeliveryState,
    WorkerClass,
)
from app.domain.scan_contract import scan_request_digest


def now_utc() -> datetime:
    return datetime.now(UTC)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class Work(Base):
    __tablename__ = "works"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_work_tenant_identity"),
        Index("ix_work_scope", "tenant_id", "catalog_id"),
        Index("ix_work_sha", "tenant_id", "sha256"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("wrk"))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    catalog_id: Mapped[str] = mapped_column(String(120), index=True)
    title: Mapped[str] = mapped_column(String(240))
    sha256: Mapped[str] = mapped_column(String(64))
    phash: Mapped[str] = mapped_column(String(32))
    storage_key: Mapped[str] = mapped_column(String(512))
    rights_path: Mapped[str] = mapped_column(String(40), default=RightsPath.NO_LICENSE_INFO)
    allowed_uses: Mapped[list[str]] = mapped_column(JSON, default=list)
    claimant: Mapped[str | None] = mapped_column(String(240), nullable=True)
    claim_state: Mapped[str] = mapped_column(String(40), default=ClaimState.ASSERTED)
    # What the enrollment AI-origin gate concluded about this file. Null for works
    # registered before the gate existed or while it was switched off, which is a
    # different thing from a work that was screened and came back quiet.
    origin_assessment: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class Scan(Base):
    __tablename__ = "scans"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_scan_tenant_identity"),
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_scan_idempotency"),
        Index("ix_scan_tenant_created", "tenant_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("scn"))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(160))
    catalog_id: Mapped[str] = mapped_column(String(120), index=True)
    intended_use: Mapped[str] = mapped_column(String(160))
    candidate_sha256: Mapped[str] = mapped_column(String(64))
    candidate_phash: Mapped[str] = mapped_column(String(32))
    candidate_storage_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    state: Mapped[str] = mapped_column(String(40), default=ScanState.QUEUED)
    match_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    policy_action: Mapped[str | None] = mapped_column(String(40), nullable=True)
    rights_path: Mapped[str | None] = mapped_column(String(40), nullable=True)
    anchor_status: Mapped[str] = mapped_column(String(40), default=AnchorStatus.NOT_REQUESTED)
    reason_codes: Mapped[list[str]] = mapped_column(JSON, default=list)
    top_match_work_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    evidence_packet: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # v0.9.3 durable-orchestration additions. All nullable so an existing v0.9.1/v0.9.2
    # database upgrades without rewriting historical rows, and `state` keeps the v1
    # vocabulary that the frontend and Evidence Packet v1 readers already consume.
    lifecycle_state: Mapped[str] = mapped_column(
        String(40), default=ScanLifecycleState.ACCEPTED, server_default=ScanLifecycleState.ACCEPTED
    )
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    principal_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    policy_version_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    catalog_version_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    corpus_snapshot_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    cancel_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    @property
    def request_digest(self) -> str:
        session = object_session(self)
        if session is not None:
            from sqlalchemy import select

            binding = session.scalar(
                select(ScanInputBinding).where(
                    ScanInputBinding.scan_id == self.id,
                    ScanInputBinding.tenant_id == self.tenant_id,
                )
            )
            if binding is not None:
                return binding.request_digest
        return scan_request_digest(
            candidate_sha256=self.candidate_sha256,
            catalog_id=self.catalog_id,
            intended_use=self.intended_use,
        )

    @property
    def submission_context(self) -> dict:
        """Declared intake facts with their provenance, never inferred residence."""
        session = object_session(self)
        capabilities = {}
        if session is not None:
            from sqlalchemy import select

            binding = session.scalar(
                select(ScanInputBinding).where(
                    ScanInputBinding.scan_id == self.id,
                    ScanInputBinding.tenant_id == self.tenant_id,
                )
            )
            capabilities = (binding.requested_capabilities or {}) if binding is not None else {}
        observation = capabilities.get("marketplace_observation") or {}
        declared_url = capabilities.get("submission_source_url")
        return {
            "country_code": capabilities.get("submission_country_code"),
            "country_basis": (
                "submitter_declaration_not_verified_residence"
                if capabilities.get("submission_country_code")
                else "not_declared"
            ),
            "source_url": observation.get("source_url") or declared_url,
            "source_kind": "marketplace" if observation else "upload",
            "source_basis": (
                "server_marketplace_observation"
                if observation
                else "submitter_url_declaration"
                if declared_url
                else "not_supplied"
            ),
            "intended_use": self.intended_use,
            "use_context": capabilities.get("use_context") or {},
        }


# ---------------------------------------------------------------------------
# S13 — identity, credentials and audit
# ---------------------------------------------------------------------------


class Principal(Base):
    """A human or service identity inside one tenant."""

    __tablename__ = "principals"
    __table_args__ = (UniqueConstraint("tenant_id", "subject", name="uq_principal_subject"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("prn"))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    subject: Mapped[str] = mapped_column(String(240))
    display_name: Mapped[str] = mapped_column(String(240))
    role: Mapped[str] = mapped_column(String(40), default=PrincipalRole.SERVICE_ACCOUNT)
    oidc_issuer: Mapped[str | None] = mapped_column(String(320), nullable=True)
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class ApiCredential(Base):
    """API key material.

    Only the prefix and a keyed digest are retained. The secret is displayed once
    at creation time and can never be recovered from this row.
    """

    __tablename__ = "api_credentials"
    __table_args__ = (Index("ix_credential_lookup", "prefix", "revoked_at"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("cred"))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    principal_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    name: Mapped[str] = mapped_column(String(160))
    prefix: Mapped[str] = mapped_column(String(24), unique=True, index=True)
    secret_digest: Mapped[str] = mapped_column(String(128))
    role: Mapped[str] = mapped_column(String(40), default=PrincipalRole.SERVICE_ACCOUNT)
    scopes: Mapped[list[str]] = mapped_column(JSON, default=list)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rotated_from_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class AuditEvent(Base):
    """Append-only security and administrative activity."""

    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_tenant_time", "tenant_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("aud"))
    tenant_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    principal_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    credential_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    event_type: Mapped[str] = mapped_column(String(60), index=True)
    resource_type: Mapped[str | None] = mapped_column(String(60), nullable=True)
    resource_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    reason: Mapped[str | None] = mapped_column(String(400), nullable=True)
    attributes: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class DeletionReceipt(Base):
    """Proof that a deletion request was executed, including retained exceptions."""

    __tablename__ = "deletion_receipts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("del"))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    requested_scope: Mapped[dict] = mapped_column(JSON, default=dict)
    state: Mapped[str] = mapped_column(String(40), default=DeletionReceiptState.REQUESTED)
    objects_deleted: Mapped[list[str]] = mapped_column(JSON, default=list)
    objects_retained: Mapped[list[dict]] = mapped_column(JSON, default=list)
    legal_hold: Mapped[bool] = mapped_column(Boolean, default=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


# ---------------------------------------------------------------------------
# S10 — versioned catalog, asset and model identities
# ---------------------------------------------------------------------------


class Catalog(Base):
    """Stable logical catalog identity."""

    __tablename__ = "catalogs"
    __table_args__ = (UniqueConstraint("tenant_id", "slug", name="uq_catalog_slug"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("cat"))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    slug: Mapped[str] = mapped_column(String(120), index=True)
    name: Mapped[str] = mapped_column(String(240))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class CatalogVersion(Base):
    """Immutable catalog membership and configuration."""

    __tablename__ = "catalog_versions"
    __table_args__ = (
        UniqueConstraint("catalog_id", "version", name="uq_catalog_version"),
        Index("ix_catalog_version_tenant", "tenant_id", "catalog_id"),
    )
    __creatorproof_immutable__ = True

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("catv"))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    catalog_id: Mapped[str] = mapped_column(String(64), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    member_count: Mapped[int] = mapped_column(Integer, default=0)
    membership_digest: Mapped[str] = mapped_column(String(64))
    configuration: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class AssetVersion(Base):
    """Immutable media bytes and normalized representation for one work."""

    __tablename__ = "asset_versions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_asset_version_tenant_identity"),
        UniqueConstraint("work_id", "version", name="uq_asset_version"),
        Index("ix_asset_version_tenant", "tenant_id", "work_id"),
    )
    __creatorproof_immutable__ = True

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("astv"))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    work_id: Mapped[str] = mapped_column(String(64), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    phash: Mapped[str] = mapped_column(String(32))
    storage_key: Mapped[str] = mapped_column(String(512))
    byte_size: Mapped[int] = mapped_column(Integer, default=0)
    media_type: Mapped[str] = mapped_column(String(80), default="image/unknown")
    width: Mapped[int] = mapped_column(Integer, default=0)
    height: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class ModelBundle(Base):
    """Exact code, weight, preprocessing and calibration identity for one provider."""

    __tablename__ = "model_bundles"
    __table_args__ = (UniqueConstraint("lane", "bundle_key", name="uq_model_bundle_key"),)
    __creatorproof_immutable__ = True

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("mdl"))
    lane: Mapped[str] = mapped_column(String(40), index=True)
    bundle_key: Mapped[str] = mapped_column(String(200))
    provider_name: Mapped[str] = mapped_column(String(200))
    qualification_state: Mapped[str] = mapped_column(String(40), default="SMOKE_TEST_ONLY")
    weight_digest: Mapped[str | None] = mapped_column(String(128), nullable=True)
    runtime_digest: Mapped[str | None] = mapped_column(String(128), nullable=True)
    preprocessing: Mapped[dict] = mapped_column(JSON, default=dict)
    calibration: Mapped[dict] = mapped_column(JSON, default=dict)
    limitations: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class CorpusSnapshotRecord(Base):
    """Durable record of exactly what was searchable for one scan."""

    __tablename__ = "corpus_snapshots"
    __creatorproof_immutable__ = True

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("snap"))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    scan_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    catalog_id: Mapped[str] = mapped_column(String(120))
    catalog_version_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    coverage_status: Mapped[str] = mapped_column(String(40))
    digest_sha256: Mapped[str] = mapped_column(String(64), index=True)
    manifest: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class ScanInputBinding(Base):
    """Immutable binding of candidate, scope, use, policy and requested capabilities."""

    __tablename__ = "scan_input_bindings"
    __creatorproof_immutable__ = True

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("bind"))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    scan_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    request_digest: Mapped[str] = mapped_column(String(64), index=True)
    candidate_sha256: Mapped[str] = mapped_column(String(64))
    catalog_id: Mapped[str] = mapped_column(String(120))
    catalog_version_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    intended_use: Mapped[str] = mapped_column(String(160))
    policy_version_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    requested_capabilities: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


# ---------------------------------------------------------------------------
# S11 — durable orchestration
# ---------------------------------------------------------------------------


class OutboxEvent(Base):
    """Transactional outbox row written in the same transaction as the business change."""

    __tablename__ = "outbox_events"
    __table_args__ = (Index("ix_outbox_dispatch", "state", "available_at"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("obx"))
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    topic: Mapped[str] = mapped_column(String(80), index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    state: Mapped[str] = mapped_column(String(40), default=OutboxState.PENDING)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(240), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class StageAttempt(Base):
    """Durable execution ledger for one stage of one scan.

    ``lease_epoch`` is monotonically increasing. Only the holder of the current
    epoch may commit a result, so a stale worker that wakes up after lease expiry
    is rejected instead of overwriting a newer attempt.
    """

    __tablename__ = "stage_attempts"
    __table_args__ = (
        UniqueConstraint("scan_id", "stage", name="uq_stage_attempt_scan_stage"),
        Index("ix_stage_lease", "state", "lease_expires_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("stg"))
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    scan_id: Mapped[str] = mapped_column(String(64), index=True)
    stage: Mapped[str] = mapped_column(String(40))
    worker_class: Mapped[str] = mapped_column(String(20), default=WorkerClass.CPU)
    state: Mapped[str] = mapped_column(String(40), default=StageState.PENDING)
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    lease_epoch: Mapped[int] = mapped_column(Integer, default=0)
    lease_owner: Mapped[str | None] = mapped_column(String(120), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    input_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    output_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    retry_class: Mapped[str | None] = mapped_column(String(40), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(160), nullable=True)
    progress_percent: Mapped[int] = mapped_column(Integer, default=0)
    progress_label: Mapped[str | None] = mapped_column(String(160), nullable=True)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


# ---------------------------------------------------------------------------
# S12 — signed statements and transparency
# ---------------------------------------------------------------------------


class SigningKey(Base):
    """Service signing key metadata. Private material stays outside the database."""

    __tablename__ = "signing_keys"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("key"))
    kid: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    algorithm: Mapped[str] = mapped_column(String(40), default="Ed25519")
    public_key_hex: Mapped[str] = mapped_column(String(256))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class EvidenceStatement(Base):
    """Immutable signed result or status update.

    Corrections, disputes, supersessions and revocations append a new row that
    references ``previous_statement_id``. A historical row is never mutated.
    """

    __tablename__ = "evidence_statements"
    __table_args__ = (
        Index("ix_statement_scan", "tenant_id", "scan_id"),
        Index("ix_statement_digest", "payload_digest_sha256"),
        Index(
            "uq_evidence_statement_successor",
            "previous_statement_id",
            unique=True,
        ),
    )
    __creatorproof_immutable__ = True

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("stm"))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    scan_id: Mapped[str] = mapped_column(String(64), index=True)
    statement_type: Mapped[str] = mapped_column(String(40), default=StatementType.RESULT)
    schema_version: Mapped[str] = mapped_column(String(60), default="creatorproof.statement.v2")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    payload_digest_sha256: Mapped[str] = mapped_column(String(64))
    signature_kid: Mapped[str | None] = mapped_column(String(80), nullable=True)
    signature_alg: Mapped[str | None] = mapped_column(String(40), nullable=True)
    signature_b64: Mapped[str | None] = mapped_column(Text, nullable=True)
    cose_sign1_b64: Mapped[str | None] = mapped_column(Text, nullable=True)
    previous_statement_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(40), default=StatementStatus.ACTIVE)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class TransparencyLeaf(Base):
    """Durable RFC 6962-style leaf. Replaces process-local JSONL as the authority."""

    __tablename__ = "transparency_leaves"
    __table_args__ = (
        UniqueConstraint("log_id", "leaf_index", name="uq_transparency_leaf_index"),
        Index("uq_transparency_leaf_statement", "log_id", "statement_id", unique=True),
    )
    __creatorproof_immutable__ = True

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("leaf"))
    log_id: Mapped[str] = mapped_column(String(80), default="creatorproof-statements", index=True)
    leaf_index: Mapped[int] = mapped_column(Integer)
    statement_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    packet_hash_sha256: Mapped[str] = mapped_column(String(64), index=True)
    leaf_hash_sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class TransparencyCheckpoint(Base):
    """Signed tree head. Consistency between checkpoints detects equivocation."""

    __tablename__ = "transparency_checkpoints"
    __table_args__ = (UniqueConstraint("log_id", "tree_size", name="uq_checkpoint_tree_size"),)
    __creatorproof_immutable__ = True

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("ckpt"))
    log_id: Mapped[str] = mapped_column(String(80), default="creatorproof-statements", index=True)
    tree_size: Mapped[int] = mapped_column(Integer)
    root_sha256: Mapped[str] = mapped_column(String(64))
    signature_kid: Mapped[str | None] = mapped_column(String(80), nullable=True)
    signature_b64: Mapped[str | None] = mapped_column(Text, nullable=True)
    external_commitment: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class IntegrityEvent(Base):
    """Immutable, signed commitment to a material domain event.

    The event payload contains identifiers and hashes, never uploaded media. Its
    digest is appended to the transparency tree; a checkpoint root can then be
    anchored once for many events instead of spending one transaction per row.
    """

    __tablename__ = "integrity_events"
    __table_args__ = (
        Index("ix_integrity_event_subject", "tenant_id", "subject_type", "subject_id"),
        Index("ix_integrity_event_digest", "payload_digest_sha256"),
    )
    __creatorproof_immutable__ = True

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("iev"))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(80), index=True)
    subject_type: Mapped[str] = mapped_column(String(40))
    subject_id: Mapped[str] = mapped_column(String(64))
    schema_version: Mapped[str] = mapped_column(
        String(80), default="creatorproof.integrity_event.v1"
    )
    payload: Mapped[dict] = mapped_column(JSON)
    payload_digest_sha256: Mapped[str] = mapped_column(String(64))
    signature_kid: Mapped[str | None] = mapped_column(String(80), nullable=True)
    signature_alg: Mapped[str | None] = mapped_column(String(40), nullable=True)
    signature_b64: Mapped[str | None] = mapped_column(Text, nullable=True)
    cose_sign1_b64: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class BlockchainAnchorJob(Base):
    """Recoverable EVM submission/reconciliation state.

    Unlike evidence records this row is deliberately mutable. A prepared
    transaction hash is committed before broadcast, preventing a crash or RPC
    timeout from silently creating duplicate attestations on retry.
    """

    __tablename__ = "blockchain_anchor_jobs"
    __table_args__ = (
        UniqueConstraint(
            "deployment_id",
            "commitment_type",
            "commitment_hash_sha256",
            name="uq_blockchain_anchor_commitment",
        ),
        Index("ix_blockchain_anchor_dispatch", "state", "available_at"),
        Index("ix_blockchain_anchor_subject", "subject_type", "subject_id"),
        CheckConstraint(
            "length(commitment_hash_sha256) = 64",
            name="ck_blockchain_anchor_commitment_hash_length",
        ),
        CheckConstraint(
            "attempts >= 0 AND max_attempts >= 1",
            name="ck_blockchain_anchor_attempts",
        ),
        CheckConstraint(
            "transaction_hash IS NULL OR length(transaction_hash) = 66",
            name="ck_blockchain_anchor_transaction_hash_length",
        ),
        CheckConstraint(
            "signed_transaction_hex IS NULL OR transaction_hash IS NOT NULL",
            name="ck_blockchain_anchor_signed_transaction_identity",
        ),
        CheckConstraint(
            "(lease_owner IS NULL AND lease_expires_at IS NULL) OR "
            "(lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL)",
            name="ck_blockchain_anchor_lease_pair",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("ban"))
    tenant_id: Mapped[str | None] = mapped_column(
        ForeignKey("tenants.id"), nullable=True, index=True
    )
    deployment_id: Mapped[str] = mapped_column(String(128))
    commitment_type: Mapped[str] = mapped_column(
        String(60), default=BlockchainCommitmentType.EVIDENCE_PACKET
    )
    commitment_hash_sha256: Mapped[str] = mapped_column(String(64), index=True)
    subject_type: Mapped[str] = mapped_column(String(40))
    subject_id: Mapped[str] = mapped_column(String(80))
    context: Mapped[dict] = mapped_column(JSON, default=dict)
    state: Mapped[str] = mapped_column(String(40), default=BlockchainAnchorJobState.PENDING)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=8)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    lease_owner: Mapped[str | None] = mapped_column(String(160), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    transaction_hash: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    signed_transaction_hex: Mapped[str | None] = mapped_column(Text, nullable=True)
    transaction_nonce: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chain_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    receipt: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, onupdate=now_utc
    )
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class NetworkMember(Base):
    """A counterparty organization allowed to co-attest, keyed by its own EVM address.

    This row is an operational mirror of the on-chain member registry, holding the
    identity metadata that deliberately never reaches the chain. When a registry
    contract is configured it, not this table, is the authority on whether an
    address may currently attest.
    """

    __tablename__ = "network_members"
    __table_args__ = (
        UniqueConstraint("tenant_id", "address", name="uq_network_member_address"),
        Index("ix_network_member_status", "tenant_id", "status"),
        CheckConstraint("length(address) = 42", name="ck_network_member_address_length"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("nmb"))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    address: Mapped[str] = mapped_column(String(42), index=True)
    org_id: Mapped[str] = mapped_column(String(120))
    display_name: Mapped[str] = mapped_column(String(240))
    role: Mapped[str] = mapped_column(String(40), default=NetworkMemberRole.BRAND)
    status: Mapped[str] = mapped_column(String(40), default=NetworkMemberStatus.ACTIVE)
    on_chain_org_id: Mapped[str | None] = mapped_column(String(66), nullable=True)
    attributes: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, onupdate=now_utc
    )


class CounterpartyAttestation(Base):
    """One counterparty's signed commitment to a clearance result.

    The signature is made with the member's own EVM key, so this row records a
    fact CreatorProof cannot fabricate. Only ``body_hash_sha256`` is committed to
    the public chain; the body, the party and any note stay here.
    """

    __tablename__ = "counterparty_attestations"
    __table_args__ = (
        UniqueConstraint("tenant_id", "body_hash_sha256", name="uq_counterparty_attestation_body"),
        Index("ix_counterparty_attestation_scan", "tenant_id", "scan_id"),
        Index("ix_counterparty_attestation_signer", "tenant_id", "signer_address"),
        CheckConstraint(
            "length(body_hash_sha256) = 64",
            name="ck_counterparty_attestation_body_hash_length",
        ),
    )
    __creatorproof_immutable__ = False

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("cpa"))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    scan_id: Mapped[str] = mapped_column(String(64), index=True)
    member_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    signer_address: Mapped[str] = mapped_column(String(42))
    party_role: Mapped[str] = mapped_column(String(40), default=NetworkMemberRole.BRAND)
    decision: Mapped[str] = mapped_column(String(60), default=CounterpartyDecision.ACKNOWLEDGED)
    packet_hash_sha256: Mapped[str] = mapped_column(String(64), index=True)
    platform_attestation_uid: Mapped[str | None] = mapped_column(String(66), nullable=True)
    body: Mapped[dict] = mapped_column(JSON, default=dict)
    body_hash_sha256: Mapped[str] = mapped_column(String(64), index=True)
    signature: Mapped[str] = mapped_column(Text)
    signature_alg: Mapped[str] = mapped_column(String(40), default="EIP712_SECP256K1")
    membership_evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    state: Mapped[str] = mapped_column(String(40), default=CounterpartyAttestationState.SIGNED)
    anchor_job_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, onupdate=now_utc
    )


class BlockchainSignerLease(Base):
    """Cross-process mutex for the one EVM signer behind a deployment."""

    __tablename__ = "blockchain_signer_leases"
    __table_args__ = (
        CheckConstraint(
            "(lease_owner IS NULL AND lease_expires_at IS NULL) OR "
            "(lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL)",
            name="ck_blockchain_signer_lease_pair",
        ),
    )

    deployment_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    lease_owner: Mapped[str | None] = mapped_column(String(160), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, onupdate=now_utc
    )


# ---------------------------------------------------------------------------
# S9 — rights, claims, licenses and policy
# ---------------------------------------------------------------------------


class Party(Base):
    """A person or organization participating in a claim or agreement.

    Identity verification is recorded separately from any authorship, ownership
    or licensing-authority assertion.
    """

    __tablename__ = "parties"
    __table_args__ = (UniqueConstraint("tenant_id", "external_ref", name="uq_party_external_ref"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("pty"))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    external_ref: Mapped[str] = mapped_column(String(240))
    display_name: Mapped[str] = mapped_column(String(240))
    party_type: Mapped[str] = mapped_column(String(40), default="INDIVIDUAL")
    verification_state: Mapped[str] = mapped_column(
        String(40), default=PartyVerificationState.UNVERIFIED
    )
    verification_evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class CreatorProfile(Base):
    """Consent-backed creator profile identity used by the resemblance lane."""

    __tablename__ = "creator_profiles"
    __table_args__ = (UniqueConstraint("tenant_id", "slug", name="uq_creator_profile_slug"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("prf"))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    slug: Mapped[str] = mapped_column(String(240), index=True)
    display_name: Mapped[str] = mapped_column(String(240))
    party_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    consent_recorded: Mapped[bool] = mapped_column(Boolean, default=False)
    consent_evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class Claim(Base):
    """A typed assertion about a work. No state means 'legal owner'."""

    __tablename__ = "claims"
    __table_args__ = (Index("ix_claim_work", "tenant_id", "work_id", "state"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("clm"))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    work_id: Mapped[str] = mapped_column(String(64), index=True)
    claimant_party_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    claimant_label: Mapped[str] = mapped_column(String(240))
    claim_type: Mapped[str] = mapped_column(String(40), default="AUTHORSHIP")
    state: Mapped[str] = mapped_column(String(40), default=ClaimState.ASSERTED)
    version: Mapped[int] = mapped_column(Integer, default=1)
    authority_level: Mapped[str] = mapped_column(String(40), default="SELF_ASSERTED")
    evidence_uri: Mapped[str | None] = mapped_column(String(512), nullable=True)
    superseded_by_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    effective_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    effective_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class License(Base):
    """Versioned recorded permission with explicit scope, term and duties."""

    __tablename__ = "licenses"
    __table_args__ = (Index("ix_license_work", "tenant_id", "work_id", "state"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("lic"))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    work_id: Mapped[str] = mapped_column(String(64), index=True)
    claim_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    grantor_party_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    state: Mapped[str] = mapped_column(String(40), default=LicenseState.ACTIVE)
    permitted_uses: Mapped[list[str]] = mapped_column(JSON, default=list)
    prohibited_uses: Mapped[list[str]] = mapped_column(JSON, default=list)
    territories: Mapped[list[str]] = mapped_column(JSON, default=list)
    channels: Mapped[list[str]] = mapped_column(JSON, default=list)
    audiences: Mapped[list[str]] = mapped_column(JSON, default=list)
    transformations: Mapped[list[str]] = mapped_column(JSON, default=list)
    duties: Mapped[list[str]] = mapped_column(JSON, default=list)
    effective_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    effective_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    superseded_by_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_uri: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class RightsEvent(Base):
    """Append-only corroboration/dispute/supersession/revocation/expiry record."""

    __tablename__ = "rights_events"
    __table_args__ = (Index("ix_rights_event_subject", "tenant_id", "subject_type", "subject_id"),)
    __creatorproof_immutable__ = True

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("rev"))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    subject_type: Mapped[str] = mapped_column(String(40))
    subject_id: Mapped[str] = mapped_column(String(64), index=True)
    event_type: Mapped[str] = mapped_column(String(40))
    actor_principal_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(400), nullable=True)
    evidence_uri: Mapped[str | None] = mapped_column(String(512), nullable=True)
    attributes: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class PolicyVersion(Base):
    """Immutable executable customer policy."""

    __tablename__ = "policy_versions"
    __table_args__ = (UniqueConstraint("tenant_id", "policy_key", "version", name="uq_policy_ver"),)
    __creatorproof_immutable__ = True

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("pol"))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    policy_key: Mapped[str] = mapped_column(String(120), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    description: Mapped[str] = mapped_column(String(400), default="")
    rules: Mapped[dict] = mapped_column(JSON, default=dict)
    block_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    digest_sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class RightsPolicyVersion(Base):
    """Immutable, machine-readable rights preferences for one registered work.

    Claims and licenses remain the authoritative evidence used by the policy
    evaluator.  This row is the versioned rights-passport projection that can be
    exported to JSON, ai.txt and TDM representations without overwriting those
    underlying facts.
    """

    __tablename__ = "rights_policy_versions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "work_id", "version", name="uq_rights_policy_work_version"),
        Index("ix_rights_policy_work", "tenant_id", "work_id", "created_at"),
        CheckConstraint("version >= 1", name="ck_rights_policy_positive_version"),
        CheckConstraint(
            "effective_from IS NULL OR effective_until IS NULL OR effective_until > effective_from",
            name="ck_rights_policy_effective_interval",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "work_id"],
            ["works.tenant_id", "works.id"],
            name="fk_rights_policy_tenant_work",
        ),
    )
    __creatorproof_immutable__ = True

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("rpol"))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    work_id: Mapped[str] = mapped_column(String(64), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    permissions: Mapped[dict] = mapped_column(JSON, default=dict)
    dimensions: Mapped[dict] = mapped_column(JSON, default=dict)
    creator_assertions: Mapped[dict] = mapped_column(JSON, default=dict)
    consent_metadata: Mapped[dict] = mapped_column(JSON, default=dict)
    revocation_metadata: Mapped[dict] = mapped_column(JSON, default=dict)
    corroboration: Mapped[list[dict]] = mapped_column(JSON, default=list)
    effective_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    effective_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    superseded_by_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    digest_sha256: Mapped[str] = mapped_column(String(64), index=True)
    created_by_principal_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class ProvenanceRecord(Base):
    """Immutable normalized result of a read-only provenance inspection."""

    __tablename__ = "provenance_records"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_provenance_tenant_identity"),
        Index("ix_provenance_subject", "tenant_id", "subject_type", "subject_id"),
        Index("ix_provenance_scan", "tenant_id", "scan_id"),
        ForeignKeyConstraint(
            ["tenant_id", "work_id"],
            ["works.tenant_id", "works.id"],
            name="fk_provenance_tenant_work",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "scan_id"],
            ["scans.tenant_id", "scans.id"],
            name="fk_provenance_tenant_scan",
        ),
    )
    __creatorproof_immutable__ = True

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("prov"))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    subject_type: Mapped[str] = mapped_column(String(40))
    subject_id: Mapped[str] = mapped_column(String(64), index=True)
    scan_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    work_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    input_sha256: Mapped[str] = mapped_column(String(64), index=True)
    provider: Mapped[str] = mapped_column(String(120))
    provider_version: Mapped[str | None] = mapped_column(String(160), nullable=True)
    status: Mapped[str] = mapped_column(String(40))
    legacy_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    reason_codes: Mapped[list[str]] = mapped_column(JSON, default=list)
    manifest_summary: Mapped[dict] = mapped_column(JSON, default=dict)
    trust_details: Mapped[dict] = mapped_column(JSON, default=dict)
    metadata_summary: Mapped[dict] = mapped_column(JSON, default=dict)
    artifact_refs: Mapped[list[dict]] = mapped_column(JSON, default=list)
    error_code: Mapped[str | None] = mapped_column(String(160), nullable=True)
    fallback_used: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class ProvenanceIngredient(Base):
    """Immutable relationship extracted from a provenance manifest."""

    __tablename__ = "provenance_ingredients"
    __table_args__ = (
        Index("ix_provenance_ingredient_record", "tenant_id", "record_id"),
        ForeignKeyConstraint(
            ["tenant_id", "record_id"],
            ["provenance_records.tenant_id", "provenance_records.id"],
            name="fk_provenance_ingredient_tenant_record",
        ),
    )
    __creatorproof_immutable__ = True

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("pvi"))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    record_id: Mapped[str] = mapped_column(String(64), index=True)
    ingredient_id: Mapped[str] = mapped_column(String(240))
    relationship: Mapped[str] = mapped_column(String(120), default="INGREDIENT")
    source_reference: Mapped[str | None] = mapped_column(String(512), nullable=True)
    input_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    trust_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    metadata_summary: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class EvidenceSignal(Base):
    """One immutable, normalized signal contributing to a scan matrix."""

    __tablename__ = "evidence_signals"
    __table_args__ = (
        UniqueConstraint("tenant_id", "signal_id", name="uq_evidence_signal_id"),
        Index("ix_evidence_signal_scan", "tenant_id", "scan_id", "lane"),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_evidence_signal_confidence_range",
        ),
        CheckConstraint(
            "started_at IS NULL OR completed_at IS NULL OR completed_at >= started_at",
            name="ck_evidence_signal_time_order",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "scan_id"],
            ["scans.tenant_id", "scans.id"],
            name="fk_evidence_signal_tenant_scan",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "matrix_id"],
            ["evidence_matrices.tenant_id", "evidence_matrices.id"],
            name="fk_evidence_signal_tenant_matrix",
        ),
    )
    __creatorproof_immutable__ = True

    signal_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    scan_id: Mapped[str] = mapped_column(String(64), index=True)
    matrix_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    lane: Mapped[str] = mapped_column(String(40), index=True)
    provider: Mapped[str] = mapped_column(String(120))
    provider_version: Mapped[str | None] = mapped_column(String(160), nullable=True)
    signal_type: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(40))
    score: Mapped[float | None] = mapped_column(nullable=True)
    score_semantics: Mapped[str | None] = mapped_column(String(160), nullable=True)
    confidence: Mapped[float | None] = mapped_column(nullable=True)
    confidence_level: Mapped[str | None] = mapped_column(String(40), nullable=True)
    evidence_quality: Mapped[str | None] = mapped_column(String(40), nullable=True)
    coverage_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    coverage: Mapped[dict] = mapped_column(JSON, default=dict)
    reason_codes: Mapped[list[str]] = mapped_column(JSON, default=list)
    artifact_refs: Mapped[list[dict]] = mapped_column(JSON, default=list)
    input_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(160), nullable=True)
    fallback_used: Mapped[bool] = mapped_column(Boolean, default=False)
    model_version: Mapped[str | None] = mapped_column(String(160), nullable=True)
    rule_version: Mapped[str | None] = mapped_column(String(160), nullable=True)
    model_or_rule_identifier: Mapped[str | None] = mapped_column(String(160), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class EvidenceCoverage(Base):
    """Immutable provider/lane coverage accounting for a scan."""

    __tablename__ = "evidence_coverages"
    __table_args__ = (
        Index("ix_evidence_coverage_scan", "tenant_id", "scan_id", "lane"),
        CheckConstraint(
            "coverage_percent IS NULL OR (coverage_percent >= 0 AND coverage_percent <= 100)",
            name="ck_evidence_coverage_percent_range",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "scan_id"],
            ["scans.tenant_id", "scans.id"],
            name="fk_evidence_coverage_tenant_scan",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "matrix_id"],
            ["evidence_matrices.tenant_id", "evidence_matrices.id"],
            name="fk_evidence_coverage_tenant_matrix",
        ),
    )
    __creatorproof_immutable__ = True

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("ecv"))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    scan_id: Mapped[str] = mapped_column(String(64), index=True)
    matrix_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    lane: Mapped[str] = mapped_column(String(40))
    provider: Mapped[str] = mapped_column(String(120))
    requested_scope: Mapped[dict] = mapped_column(JSON, default=dict)
    completed_scope: Mapped[dict] = mapped_column(JSON, default=dict)
    unavailable_scope: Mapped[dict] = mapped_column(JSON, default=dict)
    coverage_percent: Mapped[float | None] = mapped_column(nullable=True)
    reason_codes: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class EvidenceMatrix(Base):
    """Immutable finalized normalized evidence decision for a scan."""

    __tablename__ = "evidence_matrices"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_evidence_matrix_tenant_identity"),
        UniqueConstraint("tenant_id", "scan_id", "version", name="uq_evidence_matrix_scan_version"),
        CheckConstraint("version >= 1", name="ck_evidence_matrix_positive_version"),
        ForeignKeyConstraint(
            ["tenant_id", "scan_id"],
            ["scans.tenant_id", "scans.id"],
            name="fk_evidence_matrix_tenant_scan",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "previous_matrix_id"],
            ["evidence_matrices.tenant_id", "evidence_matrices.id"],
            name="fk_evidence_matrix_tenant_predecessor",
        ),
    )
    __creatorproof_immutable__ = True

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("emat"))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    scan_id: Mapped[str] = mapped_column(String(64), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    previous_matrix_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    matrix_version: Mapped[str] = mapped_column(
        String(80), default="creatorproof.evidence_matrix.v1"
    )
    final_status: Mapped[str] = mapped_column(String(80))
    abstention: Mapped[bool] = mapped_column(Boolean, default=False)
    abstention_code: Mapped[str | None] = mapped_column(String(120), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    recommended_action: Mapped[str | None] = mapped_column(String(80), nullable=True)
    policy_decision_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    packet_hash_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    coverage_summary: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ContributionEvent(Base):
    """Append-only factual contribution event forming a per-work hash chain."""

    __tablename__ = "contribution_events"
    __table_args__ = (
        UniqueConstraint("tenant_id", "event_id", name="uq_contribution_event_id"),
        UniqueConstraint("tenant_id", "work_id", "sequence", name="uq_contribution_work_sequence"),
        Index("ix_contribution_work_sequence", "tenant_id", "work_id", "sequence"),
        CheckConstraint("sequence >= 1", name="ck_contribution_positive_sequence"),
        ForeignKeyConstraint(
            ["tenant_id", "work_id"],
            ["works.tenant_id", "works.id"],
            name="fk_contribution_tenant_work",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "output_asset_id"],
            ["asset_versions.tenant_id", "asset_versions.id"],
            name="fk_contribution_tenant_output_asset",
        ),
    )
    __creatorproof_immutable__ = True

    event_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    work_id: Mapped[str] = mapped_column(String(64), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    actor_type: Mapped[str] = mapped_column(String(40))
    actor_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    event_type: Mapped[str] = mapped_column(String(80))
    description: Mapped[str] = mapped_column(Text, default="")
    classification: Mapped[str] = mapped_column(String(80), default="UNKNOWN")
    provider: Mapped[str | None] = mapped_column(String(120), nullable=True)
    model: Mapped[str | None] = mapped_column(String(160), nullable=True)
    input_asset_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    output_asset_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    software_or_model: Mapped[str | None] = mapped_column(String(240), nullable=True)
    human_decision: Mapped[str | None] = mapped_column(Text, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    evidence_artifact_reference: Mapped[str | None] = mapped_column(String(512), nullable=True)
    c2pa_reference: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(160), nullable=True)
    input_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    output_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    prompt_reference: Mapped[str | None] = mapped_column(String(256), nullable=True)
    previous_event_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    event_hash: Mapped[str] = mapped_column(String(64), index=True)
    source_reference: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class InvestigationRun(Base):
    """Mutable lifecycle for one human-supervised investigation assistant run."""

    __tablename__ = "investigation_runs"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_investigation_run_tenant_identity"),
        Index("ix_investigation_run_scan", "tenant_id", "scan_id", "created_at"),
        ForeignKeyConstraint(
            ["tenant_id", "scan_id"],
            ["scans.tenant_id", "scans.id"],
            name="fk_investigation_run_tenant_scan",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("irun"))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    scan_id: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(40), default="QUEUED")
    requested_by: Mapped[str | None] = mapped_column(String(160), nullable=True)
    provider: Mapped[str] = mapped_column(String(120), default="aiand")
    model: Mapped[str | None] = mapped_column(String(160), nullable=True)
    prompt_template_version: Mapped[str] = mapped_column(String(80), default="v1")
    evidence_packet_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    input_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(160), nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class InvestigationOutput(Base):
    """Structured, hashable assistant output awaiting human disposition."""

    __tablename__ = "investigation_outputs"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_investigation_output_tenant_identity"),
        UniqueConstraint("tenant_id", "run_id", name="uq_investigation_output_run"),
        ForeignKeyConstraint(
            ["tenant_id", "run_id"],
            ["investigation_runs.tenant_id", "investigation_runs.id"],
            name="fk_investigation_output_tenant_run",
        ),
        CheckConstraint(
            "(human_decision IS NULL AND human_decision_by IS NULL AND human_decision_at IS NULL) "
            "OR (human_decision IN ('ACCEPTED', 'EDITED', 'REJECTED') "
            "AND human_decision_by IS NOT NULL AND human_decision_at IS NOT NULL)",
            name="ck_investigation_output_human_decision",
        ),
    )
    __creatorproof_immutable__ = True

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("iout"))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    summary: Mapped[str] = mapped_column(Text, default="")
    evidence_references: Mapped[list[dict]] = mapped_column(JSON, default=list)
    missing_facts: Mapped[list[str]] = mapped_column(JSON, default=list)
    next_steps: Mapped[list[str]] = mapped_column(JSON, default=list)
    duplicate_groups: Mapped[list[dict]] = mapped_column(JSON, default=list)
    factual_notice_draft: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    unsupported_claims: Mapped[list[str]] = mapped_column(JSON, default=list)
    output_hash: Mapped[str] = mapped_column(String(64), index=True)
    provider: Mapped[str] = mapped_column(String(120))
    model: Mapped[str | None] = mapped_column(String(160), nullable=True)
    human_decision: Mapped[str | None] = mapped_column(String(32), nullable=True)
    human_decision_by: Mapped[str | None] = mapped_column(String(160), nullable=True)
    human_decision_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class PublicVerificationToken(Base):
    """Revocable, tenant-scoped token for the redacted public verifier."""

    __tablename__ = "public_verification_tokens"
    __table_args__ = (
        Index("ix_public_verification_token_lookup", "token_hash"),
        Index("ix_public_verification_resource", "tenant_id", "resource_type", "resource_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("pvt"))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    resource_type: Mapped[str] = mapped_column(String(40))
    resource_id: Mapped[str] = mapped_column(String(64), index=True)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True)
    scopes: Mapped[list[str]] = mapped_column(JSON, default=list)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_by: Mapped[str | None] = mapped_column(String(160), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


# ---------------------------------------------------------------------------
# S16 — reviewer workflow and integrations
# ---------------------------------------------------------------------------


class ReviewCase(Base):
    """Human workflow around one scan result."""

    __tablename__ = "review_cases"
    __table_args__ = (
        UniqueConstraint("tenant_id", "scan_id", name="uq_review_case_scan"),
        Index("ix_review_case_state", "tenant_id", "state", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("case"))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    scan_id: Mapped[str] = mapped_column(String(64), index=True)
    statement_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    state: Mapped[str] = mapped_column(String(40), default=ReviewCaseState.OPEN)
    priority: Mapped[str] = mapped_column(String(20), default="NORMAL")
    assignee_principal_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    disposition: Mapped[str] = mapped_column(String(40), default=ReviewDisposition.NOT_DECIDED)
    opened_reason: Mapped[str] = mapped_column(String(200), default="POLICY_REVIEW")
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ReviewEvent(Base):
    """Immutable reviewer action. Every action is attributable."""

    __tablename__ = "review_events"
    __table_args__ = (Index("ix_review_event_case", "case_id", "created_at"),)
    __creatorproof_immutable__ = True

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("cev"))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    case_id: Mapped[str] = mapped_column(String(64), index=True)
    event_type: Mapped[str] = mapped_column(String(40))
    actor_principal_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    actor_label: Mapped[str] = mapped_column(String(240), default="unknown")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    disposition: Mapped[str | None] = mapped_column(String(40), nullable=True)
    attributes: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class MarketplaceAsset(Base):
    """Durable, tenant-scoped history for a monitored provider result."""

    __tablename__ = "marketplace_assets"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "provider", "external_id", name="uq_marketplace_asset_source"
        ),
        Index("ix_marketplace_asset_tenant_seen", "tenant_id", "last_seen_at"),
        Index("ix_marketplace_asset_classification", "tenant_id", "classification"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("mas"))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    provider: Mapped[str] = mapped_column(String(24))
    external_id: Mapped[str] = mapped_column(String(100))
    title: Mapped[str] = mapped_column(String(240), default="")
    source_url: Mapped[str] = mapped_column(String(512))
    image_url: Mapped[str] = mapped_column(String(1024))
    thumbnail_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    creator: Mapped[str | None] = mapped_column(String(240), nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    provider_metadata: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    observation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    scan_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    classification: Mapped[str] = mapped_column(String(40), default="UNCLASSIFIED")
    country_code: Mapped[str | None] = mapped_column(String(2), nullable=True)
    jurisdiction_basis: Mapped[str | None] = mapped_column(String(240), nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class TakedownDraft(Base):
    """Reviewable notice text; sending remains an explicit operator action."""

    __tablename__ = "takedown_drafts"
    __table_args__ = (
        Index("ix_takedown_draft_tenant_created", "tenant_id", "created_at"),
        ForeignKeyConstraint(
            ["tenant_id", "investigation_output_id"],
            ["investigation_outputs.tenant_id", "investigation_outputs.id"],
            name="fk_takedown_draft_tenant_investigation_output",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("tdr"))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    marketplace_asset_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    scan_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    investigation_output_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )
    jurisdiction: Mapped[str] = mapped_column(String(40))
    recipient_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    recipient_country_code: Mapped[str | None] = mapped_column(String(2), nullable=True)
    subject: Mapped[str] = mapped_column(String(320))
    body: Mapped[str] = mapped_column(Text)
    generation_provider: Mapped[str] = mapped_column(String(40), default="template")
    generation_model: Mapped[str | None] = mapped_column(String(160), nullable=True)
    state: Mapped[str] = mapped_column(String(32), default="DRAFT")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class WebhookEndpoint(Base):
    """Customer webhook target. The signing secret is stored for HMAC generation."""

    __tablename__ = "webhook_endpoints"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("whk"))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    url: Mapped[str] = mapped_column(String(512))
    secret: Mapped[str] = mapped_column(String(128))
    event_types: Mapped[list[str]] = mapped_column(JSON, default=list)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class WebhookDelivery(Base):
    """One delivery attempt chain with replay-safe delivery identity."""

    __tablename__ = "webhook_deliveries"
    __table_args__ = (Index("ix_webhook_delivery_state", "state", "next_attempt_at"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("whd"))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    endpoint_id: Mapped[str] = mapped_column(String(64), index=True)
    event_type: Mapped[str] = mapped_column(String(60))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    state: Mapped[str] = mapped_column(String(40), default=WebhookDeliveryState.PENDING)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    response_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(240), nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# ---------------------------------------------------------------------------
# S17 — usage metering
# ---------------------------------------------------------------------------


class UsageRecord(Base):
    """Per-tenant metered unit used for plan limits and unit-economics reporting."""

    __tablename__ = "usage_records"
    __table_args__ = (Index("ix_usage_tenant_time", "tenant_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("use"))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    meter: Mapped[str] = mapped_column(String(60), index=True)
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    scan_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    attributes: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class ImmutableRecordError(RuntimeError):
    """Raised when application code tries to mutate an append-only row."""


def _immutable_tables() -> set[str]:
    return {
        mapper.class_.__tablename__
        for mapper in Base.registry.mappers
        if getattr(mapper.class_, "__creatorproof_immutable__", False)
    }


@event.listens_for(Base, "before_update", propagate=True)
def _reject_immutable_update(mapper, connection, target) -> None:  # noqa: ARG001
    """Application-level guard against in-place mutation of append-only records.

    Correction, dispute, supersession and revocation must append a new row that
    references the previous one. PostgreSQL adds a matching rule-level guard in
    the migration; this listener keeps SQLite development honest too.
    """
    if isinstance(target, InvestigationOutput):
        state = sa_inspect(target)
        changed = {
            attribute.key
            for attribute in state.mapper.column_attrs
            if state.attrs[attribute.key].history.has_changes()
        }
        if not changed:
            return
        decision_fields = {"human_decision", "human_decision_by", "human_decision_at"}
        original_decision = connection.execute(
            InvestigationOutput.__table__.select()
            .with_only_columns(InvestigationOutput.__table__.c.human_decision)
            .where(InvestigationOutput.__table__.c.id == target.id)
        ).scalar_one()
        if (
            changed <= decision_fields
            and original_decision is None
            and target.human_decision in {"ACCEPTED", "EDITED", "REJECTED"}
            and target.human_decision_by
            and target.human_decision_at is not None
        ):
            return
        raise ImmutableRecordError(
            "investigation_outputs content is immutable; only the first attributable "
            "human disposition is permitted"
        )
    if isinstance(target, TransparencyCheckpoint):
        state = sa_inspect(target)
        changed = {
            attribute.key
            for attribute in state.mapper.column_attrs
            if state.attrs[attribute.key].history.has_changes()
        }
        history = state.attrs.external_commitment.history
        previous = history.deleted[0] if history.deleted else None
        if (
            changed == {"external_commitment"}
            and previous is None
            and target.external_commitment is not None
        ):
            return
    if getattr(type(target), "__creatorproof_immutable__", False):
        raise ImmutableRecordError(
            f"{type(target).__tablename__} is append-only; issue a new record instead"
        )


@event.listens_for(Base, "before_delete", propagate=True)
def _reject_immutable_delete(mapper, connection, target) -> None:  # noqa: ARG001
    """SQLite and ORM paths must reject deletion as well as mutation."""
    if getattr(type(target), "__creatorproof_immutable__", False):
        raise ImmutableRecordError(
            f"{type(target).__tablename__} is append-only; issue a revocation event instead"
        )


@event.listens_for(BlockchainAnchorJob, "before_update")
def _reject_blockchain_transaction_identity_rewrite(mapper, connection, target) -> None:  # noqa: ARG001
    """A prepared signed transaction is write-once crash-recovery material."""
    state = sa_inspect(target)
    for field in (
        "transaction_hash",
        "signed_transaction_hex",
        "transaction_nonce",
        "chain_id",
    ):
        history = state.attrs[field].history
        if not history.has_changes() or not history.deleted:
            continue
        original = history.deleted[0]
        if original is not None and getattr(target, field) != original:
            raise ImmutableRecordError(
                f"blockchain_anchor_jobs.{field} is immutable after transaction preparation"
            )
