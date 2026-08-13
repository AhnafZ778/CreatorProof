"""Versioned platform entities, durable orchestration, signing and reviewer workflow.

Additive only. No legacy column is dropped and no existing row is rewritten, so a
v0.9.1/v0.9.2 database upgrades in place and existing Evidence Packet v1 rows stay
readable. The new ``scans`` columns are nullable or defaulted for the same reason.

Revision ID: 0002_platform_entities
Revises: 0001_baseline
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_platform_entities"
down_revision: str | None = "0001_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NEW_TABLES = (
    "principals",
    "api_credentials",
    "audit_events",
    "deletion_receipts",
    "catalogs",
    "catalog_versions",
    "asset_versions",
    "model_bundles",
    "corpus_snapshots",
    "scan_input_bindings",
    "outbox_events",
    "stage_attempts",
    "signing_keys",
    "evidence_statements",
    "transparency_leaves",
    "transparency_checkpoints",
    "parties",
    "creator_profiles",
    "claims",
    "licenses",
    "rights_events",
    "policy_versions",
    "review_cases",
    "review_events",
    "webhook_endpoints",
    "webhook_deliveries",
    "usage_records",
)

_NEW_SCAN_COLUMNS: tuple[tuple[str, sa.Column], ...] = (
    (
        "lifecycle_state",
        sa.Column(
            "lifecycle_state", sa.String(40), nullable=False, server_default="ACCEPTED"
        ),
    ),
    ("correlation_id", sa.Column("correlation_id", sa.String(64), nullable=True)),
    ("principal_id", sa.Column("principal_id", sa.String(64), nullable=True)),
    ("policy_version_id", sa.Column("policy_version_id", sa.String(64), nullable=True)),
    ("catalog_version_id", sa.Column("catalog_version_id", sa.String(64), nullable=True)),
    ("corpus_snapshot_id", sa.Column("corpus_snapshot_id", sa.String(64), nullable=True)),
    (
        "cancel_requested_at",
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True),
    ),
    ("deadline_at", sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=True)),
)


def _existing_tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _existing_columns(table: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if table not in inspector.get_table_names():
        return set()
    return {column["name"] for column in inspector.get_columns(table)}


def _timestamps() -> sa.Column:
    return sa.Column("created_at", sa.DateTime(timezone=True), nullable=False)


def upgrade() -> None:
    existing = _existing_tables()

    def create(name: str, *columns, indexes: tuple[tuple[str, list[str], bool], ...] = ()) -> None:
        if name in existing:
            return
        op.create_table(name, *columns)
        for index_name, index_columns, unique in indexes:
            op.create_index(index_name, name, index_columns, unique=unique)

    # -- identity, credentials, audit -------------------------------------------------
    create(
        "principals",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("subject", sa.String(240), nullable=False),
        sa.Column("display_name", sa.String(240), nullable=False),
        sa.Column("role", sa.String(40), nullable=False),
        sa.Column("oidc_issuer", sa.String(320), nullable=True),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        _timestamps(),
        sa.UniqueConstraint("tenant_id", "subject", name="uq_principal_subject"),
        indexes=(("ix_principals_tenant_id", ["tenant_id"], False),),
    )
    create(
        "api_credentials",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("principal_id", sa.String(64), nullable=True),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("prefix", sa.String(24), nullable=False, unique=True),
        sa.Column("secret_digest", sa.String(128), nullable=False),
        sa.Column("role", sa.String(40), nullable=False),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rotated_from_id", sa.String(64), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        _timestamps(),
        indexes=(
            ("ix_api_credentials_tenant_id", ["tenant_id"], False),
            ("ix_api_credentials_prefix", ["prefix"], True),
            ("ix_credential_lookup", ["prefix", "revoked_at"], False),
        ),
    )
    create(
        "audit_events",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=True),
        sa.Column("principal_id", sa.String(64), nullable=True),
        sa.Column("credential_id", sa.String(64), nullable=True),
        sa.Column("event_type", sa.String(60), nullable=False),
        sa.Column("resource_type", sa.String(60), nullable=True),
        sa.Column("resource_id", sa.String(64), nullable=True),
        sa.Column("correlation_id", sa.String(64), nullable=True),
        sa.Column("reason", sa.String(400), nullable=True),
        sa.Column("attributes", sa.JSON(), nullable=False),
        _timestamps(),
        indexes=(
            ("ix_audit_events_tenant_id", ["tenant_id"], False),
            ("ix_audit_events_event_type", ["event_type"], False),
            ("ix_audit_events_correlation_id", ["correlation_id"], False),
            ("ix_audit_tenant_time", ["tenant_id", "created_at"], False),
        ),
    )
    create(
        "deletion_receipts",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("requested_scope", sa.JSON(), nullable=False),
        sa.Column("state", sa.String(40), nullable=False),
        sa.Column("objects_deleted", sa.JSON(), nullable=False),
        sa.Column("objects_retained", sa.JSON(), nullable=False),
        sa.Column("legal_hold", sa.Boolean(), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        _timestamps(),
        indexes=(("ix_deletion_receipts_tenant_id", ["tenant_id"], False),),
    )

    # -- versioned catalog, asset and model identities --------------------------------
    create(
        "catalogs",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("slug", sa.String(120), nullable=False),
        sa.Column("name", sa.String(240), nullable=False),
        _timestamps(),
        sa.UniqueConstraint("tenant_id", "slug", name="uq_catalog_slug"),
        indexes=(
            ("ix_catalogs_tenant_id", ["tenant_id"], False),
            ("ix_catalogs_slug", ["slug"], False),
        ),
    )
    create(
        "catalog_versions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("catalog_id", sa.String(64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("member_count", sa.Integer(), nullable=False),
        sa.Column("membership_digest", sa.String(64), nullable=False),
        sa.Column("configuration", sa.JSON(), nullable=False),
        _timestamps(),
        sa.UniqueConstraint("catalog_id", "version", name="uq_catalog_version"),
        indexes=(
            ("ix_catalog_versions_tenant_id", ["tenant_id"], False),
            ("ix_catalog_versions_catalog_id", ["catalog_id"], False),
            ("ix_catalog_version_tenant", ["tenant_id", "catalog_id"], False),
        ),
    )
    create(
        "asset_versions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("work_id", sa.String(64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("phash", sa.String(32), nullable=False),
        sa.Column("storage_key", sa.String(512), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("media_type", sa.String(80), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        _timestamps(),
        sa.UniqueConstraint("work_id", "version", name="uq_asset_version"),
        indexes=(
            ("ix_asset_versions_tenant_id", ["tenant_id"], False),
            ("ix_asset_versions_work_id", ["work_id"], False),
            ("ix_asset_versions_sha256", ["sha256"], False),
            ("ix_asset_version_tenant", ["tenant_id", "work_id"], False),
        ),
    )
    create(
        "model_bundles",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("lane", sa.String(40), nullable=False),
        sa.Column("bundle_key", sa.String(200), nullable=False),
        sa.Column("provider_name", sa.String(200), nullable=False),
        sa.Column("qualification_state", sa.String(40), nullable=False),
        sa.Column("weight_digest", sa.String(128), nullable=True),
        sa.Column("runtime_digest", sa.String(128), nullable=True),
        sa.Column("preprocessing", sa.JSON(), nullable=False),
        sa.Column("calibration", sa.JSON(), nullable=False),
        sa.Column("limitations", sa.JSON(), nullable=False),
        _timestamps(),
        sa.UniqueConstraint("lane", "bundle_key", name="uq_model_bundle_key"),
        indexes=(("ix_model_bundles_lane", ["lane"], False),),
    )
    create(
        "corpus_snapshots",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("scan_id", sa.String(64), nullable=True),
        sa.Column("catalog_id", sa.String(120), nullable=False),
        sa.Column("catalog_version_id", sa.String(64), nullable=True),
        sa.Column("coverage_status", sa.String(40), nullable=False),
        sa.Column("digest_sha256", sa.String(64), nullable=False),
        sa.Column("manifest", sa.JSON(), nullable=False),
        _timestamps(),
        indexes=(
            ("ix_corpus_snapshots_tenant_id", ["tenant_id"], False),
            ("ix_corpus_snapshots_scan_id", ["scan_id"], False),
            ("ix_corpus_snapshots_digest_sha256", ["digest_sha256"], False),
        ),
    )
    create(
        "scan_input_bindings",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("scan_id", sa.String(64), nullable=False, unique=True),
        sa.Column("request_digest", sa.String(64), nullable=False),
        sa.Column("candidate_sha256", sa.String(64), nullable=False),
        sa.Column("catalog_id", sa.String(120), nullable=False),
        sa.Column("catalog_version_id", sa.String(64), nullable=True),
        sa.Column("intended_use", sa.String(160), nullable=False),
        sa.Column("policy_version_id", sa.String(64), nullable=True),
        sa.Column("requested_capabilities", sa.JSON(), nullable=False),
        _timestamps(),
        indexes=(
            ("ix_scan_input_bindings_tenant_id", ["tenant_id"], False),
            ("ix_scan_input_bindings_scan_id", ["scan_id"], True),
            ("ix_scan_input_bindings_request_digest", ["request_digest"], False),
        ),
    )

    # -- durable orchestration ---------------------------------------------------------
    create(
        "outbox_events",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("topic", sa.String(80), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("state", sa.String(40), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(240), nullable=True),
        _timestamps(),
        indexes=(
            ("ix_outbox_events_tenant_id", ["tenant_id"], False),
            ("ix_outbox_events_topic", ["topic"], False),
            ("ix_outbox_dispatch", ["state", "available_at"], False),
        ),
    )
    create(
        "stage_attempts",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("scan_id", sa.String(64), nullable=False),
        sa.Column("stage", sa.String(40), nullable=False),
        sa.Column("worker_class", sa.String(20), nullable=False),
        sa.Column("state", sa.String(40), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("lease_epoch", sa.Integer(), nullable=False),
        sa.Column("lease_owner", sa.String(120), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("input_digest", sa.String(64), nullable=True),
        sa.Column("output_digest", sa.String(64), nullable=True),
        sa.Column("retry_class", sa.String(40), nullable=True),
        sa.Column("error_code", sa.String(160), nullable=True),
        sa.Column("progress_percent", sa.Integer(), nullable=False),
        sa.Column("progress_label", sa.String(160), nullable=True),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        _timestamps(),
        sa.UniqueConstraint("scan_id", "stage", name="uq_stage_attempt_scan_stage"),
        indexes=(
            ("ix_stage_attempts_tenant_id", ["tenant_id"], False),
            ("ix_stage_attempts_scan_id", ["scan_id"], False),
            ("ix_stage_lease", ["state", "lease_expires_at"], False),
        ),
    )

    # -- signing and transparency ------------------------------------------------------
    create(
        "signing_keys",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("kid", sa.String(80), nullable=False, unique=True),
        sa.Column("algorithm", sa.String(40), nullable=False),
        sa.Column("public_key_hex", sa.String(256), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        _timestamps(),
        indexes=(("ix_signing_keys_kid", ["kid"], True),),
    )
    create(
        "evidence_statements",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("scan_id", sa.String(64), nullable=False),
        sa.Column("statement_type", sa.String(40), nullable=False),
        sa.Column("schema_version", sa.String(60), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("payload_digest_sha256", sa.String(64), nullable=False),
        sa.Column("signature_kid", sa.String(80), nullable=True),
        sa.Column("signature_alg", sa.String(40), nullable=True),
        sa.Column("signature_b64", sa.Text(), nullable=True),
        sa.Column("cose_sign1_b64", sa.Text(), nullable=True),
        sa.Column("previous_statement_id", sa.String(64), nullable=True),
        sa.Column("status", sa.String(40), nullable=False),
        _timestamps(),
        indexes=(
            ("ix_evidence_statements_tenant_id", ["tenant_id"], False),
            ("ix_evidence_statements_scan_id", ["scan_id"], False),
            ("ix_statement_scan", ["tenant_id", "scan_id"], False),
            ("ix_statement_digest", ["payload_digest_sha256"], False),
        ),
    )
    create(
        "transparency_leaves",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("log_id", sa.String(80), nullable=False),
        sa.Column("leaf_index", sa.Integer(), nullable=False),
        sa.Column("statement_id", sa.String(64), nullable=True),
        sa.Column("packet_hash_sha256", sa.String(64), nullable=False),
        sa.Column("leaf_hash_sha256", sa.String(64), nullable=False),
        _timestamps(),
        sa.UniqueConstraint("log_id", "leaf_index", name="uq_transparency_leaf_index"),
        indexes=(
            ("ix_transparency_leaves_log_id", ["log_id"], False),
            ("ix_transparency_leaves_statement_id", ["statement_id"], False),
            ("ix_transparency_leaves_packet_hash_sha256", ["packet_hash_sha256"], False),
        ),
    )
    create(
        "transparency_checkpoints",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("log_id", sa.String(80), nullable=False),
        sa.Column("tree_size", sa.Integer(), nullable=False),
        sa.Column("root_sha256", sa.String(64), nullable=False),
        sa.Column("signature_kid", sa.String(80), nullable=True),
        sa.Column("signature_b64", sa.Text(), nullable=True),
        sa.Column("external_commitment", sa.JSON(), nullable=True),
        _timestamps(),
        sa.UniqueConstraint("log_id", "tree_size", name="uq_checkpoint_tree_size"),
        indexes=(("ix_transparency_checkpoints_log_id", ["log_id"], False),),
    )

    # -- rights domain -----------------------------------------------------------------
    create(
        "parties",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("external_ref", sa.String(240), nullable=False),
        sa.Column("display_name", sa.String(240), nullable=False),
        sa.Column("party_type", sa.String(40), nullable=False),
        sa.Column("verification_state", sa.String(40), nullable=False),
        sa.Column("verification_evidence", sa.JSON(), nullable=False),
        _timestamps(),
        sa.UniqueConstraint("tenant_id", "external_ref", name="uq_party_external_ref"),
        indexes=(("ix_parties_tenant_id", ["tenant_id"], False),),
    )
    create(
        "creator_profiles",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("slug", sa.String(240), nullable=False),
        sa.Column("display_name", sa.String(240), nullable=False),
        sa.Column("party_id", sa.String(64), nullable=True),
        sa.Column("consent_recorded", sa.Boolean(), nullable=False),
        sa.Column("consent_evidence", sa.JSON(), nullable=False),
        _timestamps(),
        sa.UniqueConstraint("tenant_id", "slug", name="uq_creator_profile_slug"),
        indexes=(
            ("ix_creator_profiles_tenant_id", ["tenant_id"], False),
            ("ix_creator_profiles_slug", ["slug"], False),
        ),
    )
    create(
        "claims",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("work_id", sa.String(64), nullable=False),
        sa.Column("claimant_party_id", sa.String(64), nullable=True),
        sa.Column("claimant_label", sa.String(240), nullable=False),
        sa.Column("claim_type", sa.String(40), nullable=False),
        sa.Column("state", sa.String(40), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("authority_level", sa.String(40), nullable=False),
        sa.Column("evidence_uri", sa.String(512), nullable=True),
        sa.Column("superseded_by_id", sa.String(64), nullable=True),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("effective_until", sa.DateTime(timezone=True), nullable=True),
        _timestamps(),
        indexes=(
            ("ix_claims_tenant_id", ["tenant_id"], False),
            ("ix_claims_work_id", ["work_id"], False),
            ("ix_claim_work", ["tenant_id", "work_id", "state"], False),
        ),
    )
    create(
        "licenses",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("work_id", sa.String(64), nullable=False),
        sa.Column("claim_id", sa.String(64), nullable=True),
        sa.Column("grantor_party_id", sa.String(64), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(40), nullable=False),
        sa.Column("permitted_uses", sa.JSON(), nullable=False),
        sa.Column("prohibited_uses", sa.JSON(), nullable=False),
        sa.Column("territories", sa.JSON(), nullable=False),
        sa.Column("channels", sa.JSON(), nullable=False),
        sa.Column("audiences", sa.JSON(), nullable=False),
        sa.Column("transformations", sa.JSON(), nullable=False),
        sa.Column("duties", sa.JSON(), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("effective_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("superseded_by_id", sa.String(64), nullable=True),
        sa.Column("source_uri", sa.String(512), nullable=True),
        _timestamps(),
        indexes=(
            ("ix_licenses_tenant_id", ["tenant_id"], False),
            ("ix_licenses_work_id", ["work_id"], False),
            ("ix_license_work", ["tenant_id", "work_id", "state"], False),
        ),
    )
    create(
        "rights_events",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("subject_type", sa.String(40), nullable=False),
        sa.Column("subject_id", sa.String(64), nullable=False),
        sa.Column("event_type", sa.String(40), nullable=False),
        sa.Column("actor_principal_id", sa.String(64), nullable=True),
        sa.Column("reason", sa.String(400), nullable=True),
        sa.Column("evidence_uri", sa.String(512), nullable=True),
        sa.Column("attributes", sa.JSON(), nullable=False),
        _timestamps(),
        indexes=(
            ("ix_rights_events_tenant_id", ["tenant_id"], False),
            ("ix_rights_events_subject_id", ["subject_id"], False),
            ("ix_rights_event_subject", ["tenant_id", "subject_type", "subject_id"], False),
        ),
    )
    create(
        "policy_versions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("policy_key", sa.String(120), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("description", sa.String(400), nullable=False),
        sa.Column("rules", sa.JSON(), nullable=False),
        sa.Column("block_enabled", sa.Boolean(), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("digest_sha256", sa.String(64), nullable=False),
        _timestamps(),
        sa.UniqueConstraint("tenant_id", "policy_key", "version", name="uq_policy_ver"),
        indexes=(
            ("ix_policy_versions_tenant_id", ["tenant_id"], False),
            ("ix_policy_versions_policy_key", ["policy_key"], False),
        ),
    )

    # -- reviewer workflow and integrations --------------------------------------------
    create(
        "review_cases",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("scan_id", sa.String(64), nullable=False),
        sa.Column("statement_id", sa.String(64), nullable=True),
        sa.Column("state", sa.String(40), nullable=False),
        sa.Column("priority", sa.String(20), nullable=False),
        sa.Column("assignee_principal_id", sa.String(64), nullable=True),
        sa.Column("disposition", sa.String(40), nullable=False),
        sa.Column("opened_reason", sa.String(200), nullable=False),
        sa.Column("correlation_id", sa.String(64), nullable=True),
        _timestamps(),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("tenant_id", "scan_id", name="uq_review_case_scan"),
        indexes=(
            ("ix_review_cases_tenant_id", ["tenant_id"], False),
            ("ix_review_cases_scan_id", ["scan_id"], False),
            ("ix_review_cases_correlation_id", ["correlation_id"], False),
            ("ix_review_case_state", ["tenant_id", "state", "created_at"], False),
        ),
    )
    create(
        "review_events",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("case_id", sa.String(64), nullable=False),
        sa.Column("event_type", sa.String(40), nullable=False),
        sa.Column("actor_principal_id", sa.String(64), nullable=True),
        sa.Column("actor_label", sa.String(240), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("disposition", sa.String(40), nullable=True),
        sa.Column("attributes", sa.JSON(), nullable=False),
        _timestamps(),
        indexes=(
            ("ix_review_events_tenant_id", ["tenant_id"], False),
            ("ix_review_events_case_id", ["case_id"], False),
            ("ix_review_event_case", ["case_id", "created_at"], False),
        ),
    )
    create(
        "webhook_endpoints",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("url", sa.String(512), nullable=False),
        sa.Column("secret", sa.String(128), nullable=False),
        sa.Column("event_types", sa.JSON(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        _timestamps(),
        indexes=(("ix_webhook_endpoints_tenant_id", ["tenant_id"], False),),
    )
    create(
        "webhook_deliveries",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("endpoint_id", sa.String(64), nullable=False),
        sa.Column("event_type", sa.String(60), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("state", sa.String(40), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("response_status", sa.Integer(), nullable=True),
        sa.Column("last_error", sa.String(240), nullable=True),
        sa.Column("correlation_id", sa.String(64), nullable=True),
        _timestamps(),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        indexes=(
            ("ix_webhook_deliveries_tenant_id", ["tenant_id"], False),
            ("ix_webhook_deliveries_endpoint_id", ["endpoint_id"], False),
            ("ix_webhook_deliveries_correlation_id", ["correlation_id"], False),
            ("ix_webhook_delivery_state", ["state", "next_attempt_at"], False),
        ),
    )
    create(
        "usage_records",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("meter", sa.String(60), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("scan_id", sa.String(64), nullable=True),
        sa.Column("attributes", sa.JSON(), nullable=False),
        _timestamps(),
        indexes=(
            ("ix_usage_records_tenant_id", ["tenant_id"], False),
            ("ix_usage_records_meter", ["meter"], False),
            ("ix_usage_tenant_time", ["tenant_id", "created_at"], False),
        ),
    )

    # -- additive scan columns ----------------------------------------------------------
    present = _existing_columns("scans")
    for name, column in _NEW_SCAN_COLUMNS:
        if name not in present:
            op.add_column("scans", column)
    if "ix_scans_correlation_id" not in {
        index["name"] for index in sa.inspect(op.get_bind()).get_indexes("scans")
    }:
        op.create_index("ix_scans_correlation_id", "scans", ["correlation_id"])


def downgrade() -> None:
    present = _existing_columns("scans")
    indexes = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes("scans")}
    if "ix_scans_correlation_id" in indexes:
        op.drop_index("ix_scans_correlation_id", table_name="scans")
    for name, _column in reversed(_NEW_SCAN_COLUMNS):
        if name in present:
            op.drop_column("scans", name)
    existing = _existing_tables()
    for table in reversed(_NEW_TABLES):
        if table in existing:
            op.drop_table(table)
