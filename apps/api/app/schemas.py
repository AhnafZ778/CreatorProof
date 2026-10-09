from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, computed_field, field_validator

from app.domain.enums import CapabilityExecutionState, CoverageReasonCode, CoverageStatus
from app.domain.platform import (
    CounterpartyDecision,
    CredentialScope,
    LicenseState,
    NetworkMemberRole,
    NetworkMemberStatus,
    PrincipalRole,
    ReviewCaseState,
    ReviewDisposition,
    ReviewEventType,
    StageState,
    StatementType,
)


class WorkRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    catalog_id: str
    title: str
    sha256: str
    phash: str
    rights_path: str
    allowed_uses: list[str]
    claimant: str | None
    claim_state: str
    origin_assessment: dict | None = None
    created_at: datetime


class MarketplaceProviderRead(BaseModel):
    provider: Literal["unsplash", "pixabay", "ebay"]
    configured: bool
    environment: Literal["sandbox", "production"]
    marketplace_id: str | None = None


class MarketplaceSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: Literal["unsplash", "pixabay", "ebay"]
    query: str = Field(min_length=1, max_length=100)
    page: int = Field(default=1, ge=1, le=1000)
    per_page: int = Field(default=9, ge=3, le=30)


class MarketplaceCandidateRead(BaseModel):
    observation_id: str
    provider: Literal["unsplash", "pixabay", "ebay"]
    external_id: str
    title: str
    source_url: HttpUrl
    image_url: HttpUrl
    thumbnail_url: HttpUrl | None = None
    creator: str | None = None
    width: int | None = None
    height: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class MarketplaceSearchRead(BaseModel):
    provider: Literal["unsplash", "pixabay", "ebay"]
    query: str
    page: int
    per_page: int
    results: list[MarketplaceCandidateRead]


class MarketplaceSelectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    observation_id: str = Field(pattern=r"^obs_[a-f0-9]{32}$")


class DirectUploadCreateRequest(BaseModel):
    purpose: Literal["scan", "work"]
    filename: str = Field(min_length=1, max_length=255)
    content_type: Literal["image/jpeg", "image/png", "image/webp"]
    size_bytes: int = Field(gt=0)


class DirectUploadInstruction(BaseModel):
    method: Literal["PUT"]
    url: str
    headers: dict[str, str]
    expires_seconds: int
    max_bytes: int
    max_bytes_enforced: bool = False


class DirectUploadCreatedRead(BaseModel):
    upload_token: str
    upload: DirectUploadInstruction


class ScanUseContext(BaseModel):
    """Declared use dimensions, never inferred geography or claimant authority."""

    model_config = ConfigDict(extra="forbid")

    territory: str | None = Field(default=None, min_length=2, max_length=2)
    channel: str | None = Field(default=None, min_length=1, max_length=160)
    audience: str | None = Field(default=None, min_length=1, max_length=160)
    transformation: str | None = Field(default=None, min_length=1, max_length=160)
    platform: str | None = Field(default=None, min_length=1, max_length=160)
    model: str | None = Field(default=None, min_length=1, max_length=160)
    rights_permission: str | None = Field(default=None, min_length=1, max_length=160)

    @field_validator("territory")
    @classmethod
    def normalize_territory(cls, value: str | None) -> str | None:
        if value is not None and (not value.isascii() or not value.isalpha()):
            raise ValueError("territory must be a two-letter ISO country code")
        return value.upper() if value else None

    @field_validator("channel", "audience", "transformation", "platform", "model")
    @classmethod
    def bounded_text(cls, value: str | None) -> str | None:
        if value is not None and (not value.strip() or any(ord(c) < 32 for c in value)):
            raise ValueError("Use dimensions must be nonempty text without control characters")
        return value.strip() if value else None

    @field_validator("rights_permission")
    @classmethod
    def known_permission(cls, value: str | None) -> str | None:
        from app.services.rights_passport import PERMISSION_ALIASES, PERMISSION_FIELDS

        if value is None:
            return None
        normalized = PERMISSION_ALIASES.get(value.strip(), value.strip())
        if normalized not in PERMISSION_FIELDS:
            raise ValueError("rights_permission must identify a supported rights-passport field")
        return normalized


class ScanFromUploadRequest(BaseModel):
    upload_token: str = Field(min_length=32, max_length=8192)
    catalog_id: str = Field(min_length=1, max_length=120)
    intended_use: str = Field(min_length=1, max_length=160)
    country_code: str | None = Field(default=None, min_length=2, max_length=2)
    use_context: ScanUseContext | None = None
    source_url: HttpUrl | None = Field(default=None, max_length=2048)

    @field_validator("source_url")
    @classmethod
    def public_source_declaration(cls, value: HttpUrl | None) -> HttpUrl | None:
        if value and (value.username or value.password):
            raise ValueError("source_url must not contain credentials")
        return value


class MarketplaceScanRequest(MarketplaceSelectionRequest):
    catalog_id: str = Field(min_length=1, max_length=120)
    intended_use: str = Field(min_length=1, max_length=160)
    country_code: str | None = Field(default=None, min_length=2, max_length=2)
    use_context: ScanUseContext | None = None


class WorkFromUploadRequest(BaseModel):
    upload_token: str = Field(min_length=32, max_length=8192)
    title: str = Field(min_length=1, max_length=240)
    catalog_id: str = Field(min_length=1, max_length=120)
    rights_path: str = "NO_LICENSE_INFO"
    allowed_uses: list[str] | str = Field(default_factory=list)
    claimant: str | None = Field(default=None, max_length=240)
    claim_state: str = "ASSERTED"


class CapabilityCoverageRead(BaseModel):
    model_config = ConfigDict(extra="allow")

    required: bool
    execution_state: CapabilityExecutionState


class CorpusScopeRead(BaseModel):
    model_config = ConfigDict(extra="allow")

    snapshot_id: str
    snapshot_digest_sha256: str
    created_at: datetime
    tenant_id: str
    catalog_id: str
    catalog_version: str
    coverage_status: CoverageStatus
    coverage_reason_codes: list[CoverageReasonCode]
    complete_for_declared_catalog: bool
    eligible_reference_count: int
    nominated_candidate_count: int
    verified_candidate_count: int
    omitted_candidate_count: int
    failed_candidate_count: int
    candidate_limit: int
    capabilities: dict[str, CapabilityCoverageRead]


class EvidencePacketRead(BaseModel):
    """Typed stable envelope while preserving evolving lane-specific evidence fields."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    schema_version: str | None = Field(default=None, alias="schema")
    scope: CorpusScopeRead | None = None


class FailureEvidencePacketRead(BaseModel):
    """Explicit terminal-failure envelope; it makes no successful-scope claim."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)
    schema_version: Literal["creatorproof.failure-evidence.v1"] = Field(alias="schema")
    scan_id: str
    decision: dict[str, Any]
    scope: dict[str, Any]


class AdminReviewStatusRead(BaseModel):
    saved: bool
    status: Literal["needs_review", "not_flagged", "pending", "unavailable"]
    category: Literal["CONTENT_FLAG", "ASSESSMENT_GAP"] | None
    reasons: list[str]


class ScanRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    catalog_id: str
    intended_use: str
    candidate_sha256: str
    request_digest: str
    state: str
    match_status: str | None
    policy_action: str | None
    rights_path: str | None
    anchor_status: str
    reason_codes: list[str]
    top_match_work_id: str | None
    evidence_packet: EvidencePacketRead | FailureEvidencePacketRead | None
    error_code: str | None
    created_at: datetime
    completed_at: datetime | None
    submission_context: dict[str, Any] = Field(default_factory=dict)

    @computed_field
    @property
    def admin_review(self) -> AdminReviewStatusRead:
        from app.services.admin_review import review_signal

        return AdminReviewStatusRead.model_validate(review_signal(self))


class MarketplaceScanRead(BaseModel):
    provider: Literal["unsplash", "pixabay", "ebay"]
    selected: MarketplaceCandidateRead
    scan: ScanRead


class MarketplaceMonitorRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Literal["unsplash", "pixabay", "ebay"]
    query: str = Field(min_length=1, max_length=100)
    catalog_id: str = Field(min_length=1, max_length=120)
    intended_use: str = Field(default="marketplace monitoring", min_length=1, max_length=160)
    page: int = Field(default=1, ge=1, le=1000)
    per_page: int = Field(default=9, ge=3, le=30)
    scan_new: bool = True


class MarketplaceAssetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    provider: str
    external_id: str
    title: str
    source_url: str
    image_url: str
    thumbnail_url: str | None
    creator: str | None
    width: int | None
    height: int | None
    metadata: dict[str, Any]
    observation_id: str | None
    scan_id: str | None
    classification: str
    country_code: str | None
    jurisdiction_basis: str | None
    first_seen_at: datetime
    last_seen_at: datetime


class MarketplaceMonitorRead(BaseModel):
    provider: Literal["unsplash", "pixabay", "ebay"]
    query: str
    checked_at: datetime
    new_images: list[MarketplaceAssetRead]
    history: list[MarketplaceAssetRead]
    duplicate_count: int


class DetectionWorkRead(BaseModel):
    id: str
    title: str
    claimant: str | None
    catalog_id: str
    claim_state: str
    rights_path: str
    allowed_uses: list[str]
    deleted: bool = False


class DetectionReviewCaseRead(BaseModel):
    id: str
    state: str
    disposition: str
    priority: str


class UserDetectionRead(BaseModel):
    """A completed user scan that an operator can investigate and act on."""

    scan_id: str
    country_code: str | None
    jurisdiction: str
    match_status: str | None
    policy_action: str | None
    classification: str
    candidate_sha256: str
    matched_work_id: str | None
    evidence_packet: dict[str, Any]
    created_at: datetime
    completed_at: datetime | None
    catalog_id: str
    intended_use: str
    use_context: dict[str, Any] = Field(default_factory=dict)
    submission_context: dict[str, Any] = Field(default_factory=dict)
    country_basis: str
    source_url: str | None = None
    source_provider: str | None = None
    source_metadata: dict[str, Any] = Field(default_factory=dict)
    category: Literal["CONTENT_FLAG", "ASSESSMENT_GAP"]
    flag_reasons: list[str]
    reason_codes: list[str]
    review_summary: str
    candidate_media_url: str | None
    candidate_media_status: Literal["available", "expired", "not_retained"]
    candidate_media_expires_at: datetime | None
    reference_media_url: str | None
    matched_work: DetectionWorkRead | None
    reference_work: DetectionWorkRead | None
    review_case: DetectionReviewCaseRead | None
    takedown_eligible: bool
    takedown_block_reason: str | None


class TakedownDraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    marketplace_asset_id: str | None = Field(default=None, min_length=1, max_length=64)
    scan_id: str | None = Field(default=None, min_length=1, max_length=64)
    jurisdiction: str = Field(default="GENERIC", min_length=2, max_length=40)
    claimant_name: str = Field(min_length=1, max_length=240)
    claimant_email: str = Field(min_length=3, max_length=320)
    protected_title: str = Field(min_length=1, max_length=240)
    protected_url: HttpUrl
    infringing_url: HttpUrl | None = None
    evidence_summary: str = Field(min_length=1, max_length=4000)
    recipient_email: str | None = Field(default=None, max_length=320)


class TakedownDraftRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    marketplace_asset_id: str | None
    scan_id: str | None
    jurisdiction: str
    recipient_email: str | None
    recipient_country_code: str | None
    subject: str
    body: str
    generation_provider: str
    generation_model: str | None
    investigation_output_id: str | None = None
    state: str
    created_at: datetime
    sent_at: datetime | None


class TakedownSendRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    delivery: Literal["manual", "mailto"] = "manual"
    recipient_email: str | None = Field(default=None, max_length=320)


# ---------------------------------------------------------------------------
# S11 — orchestration surface
# ---------------------------------------------------------------------------


class StageAttemptRead(BaseModel):
    model_config = ConfigDict(extra="allow")

    stage: str
    state: StageState
    worker_class: str
    attempt: int
    max_attempts: int
    progress_percent: int
    progress_label: str | None = None
    error_code: str | None = None
    retry_class: str | None = None
    output_digest: str | None = None
    started_at: str | None = None
    completed_at: str | None = None


class ScanStageTimelineRead(BaseModel):
    scan_id: str
    state: str
    lifecycle_state: str
    correlation_id: str | None = None
    deadline_at: datetime | None = None
    cancel_requested_at: datetime | None = None
    stages: list[StageAttemptRead]


class ScanCancelRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=400)


# ---------------------------------------------------------------------------
# S12 — statements and verification
# ---------------------------------------------------------------------------


class StatementStatusRequest(BaseModel):
    statement_type: StatementType
    reason: str = Field(min_length=3, max_length=400)
    statement_id: str | None = None


class StatementVerificationRead(BaseModel):
    statement_id: str
    valid: bool
    digest_matches: bool
    signature_valid: bool
    status: str
    kid: str | None = None
    reason: str | None = None
    note: str | None = None


class TransparencyConsistencyRead(BaseModel):
    log_id: str
    tree_size: int
    checkpoints_checked: int
    consistent: bool
    mismatches: list[dict]
    scope: str = "LOCAL_APPEND_ONLY_LOG_NOT_BLOCKCHAIN"


# ---------------------------------------------------------------------------
# S13 — credentials
# ---------------------------------------------------------------------------


class NetworkMemberUpsertRequest(BaseModel):
    """Local identity metadata for a counterparty that signs with its own key.

    Enrolment authority stays on chain. This only records who an address belongs
    to, which is exactly the information that must not be published.
    """

    address: str = Field(min_length=42, max_length=42, pattern=r"^0[xX][0-9a-fA-F]{40}$")
    org_id: str = Field(min_length=1, max_length=120)
    display_name: str = Field(min_length=1, max_length=240)
    role: NetworkMemberRole = NetworkMemberRole.BRAND
    status: NetworkMemberStatus = NetworkMemberStatus.ACTIVE
    attributes: dict[str, Any] = Field(default_factory=dict)


class NetworkMemberRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    address: str
    org_id: str
    display_name: str
    role: str
    status: str
    on_chain_org_id: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class CoAttestationChallengeRequest(BaseModel):
    scan_id: str = Field(min_length=1, max_length=64)
    signer_address: str = Field(min_length=42, max_length=42, pattern=r"^0[xX][0-9a-fA-F]{40}$")
    party_org_id: str = Field(default="", max_length=120)
    party_role: NetworkMemberRole = NetworkMemberRole.BRAND
    decision: CounterpartyDecision = CounterpartyDecision.ACKNOWLEDGED
    # Only the digest of any human-readable note is committed; the note itself
    # never leaves the counterparty.
    decision_note_sha256: str | None = Field(default=None, pattern=r"^(0[xX])?[0-9a-fA-F]{64}$")


class CoAttestationSubmitRequest(BaseModel):
    scan_id: str = Field(min_length=1, max_length=64)
    body: dict[str, Any]
    signature: str = Field(min_length=2, max_length=600)


class CoAttestationWithdrawRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=400)


class CredentialCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    role: PrincipalRole = PrincipalRole.SERVICE_ACCOUNT
    scopes: list[CredentialScope] = Field(default_factory=list)
    expires_in_days: int | None = Field(default=None, ge=1, le=3650)
    rotates_credential_id: str | None = None


class CredentialRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    prefix: str
    role: str
    scopes: list[str]
    expires_at: datetime | None
    revoked_at: datetime | None
    last_used_at: datetime | None
    created_at: datetime


class CredentialCreatedRead(BaseModel):
    credential: CredentialRead
    api_key: str
    warning: str = (
        "This secret is shown once and is not recoverable. Only a prefix and a keyed "
        "digest are stored."
    )


class DeletionReceiptRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    state: str
    requested_scope: dict
    objects_deleted: list[str]
    objects_retained: list[dict]
    legal_hold: bool
    verified_at: datetime | None
    created_at: datetime


# ---------------------------------------------------------------------------
# S9 — rights domain
# ---------------------------------------------------------------------------


class PartyCreateRequest(BaseModel):
    external_ref: str = Field(min_length=1, max_length=240)
    display_name: str = Field(min_length=1, max_length=240)
    party_type: Literal["INDIVIDUAL", "ORGANIZATION", "AGENCY", "MARKETPLACE"] = "INDIVIDUAL"


class PartyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    external_ref: str
    display_name: str
    party_type: str
    verification_state: str
    created_at: datetime


class ClaimCreateRequest(BaseModel):
    work_id: str
    claimant_label: str = Field(min_length=1, max_length=240)
    claimant_party_id: str | None = None
    claim_type: Literal["AUTHORSHIP", "RIGHTS_MANAGEMENT", "DISTRIBUTION", "AGENCY"] = "AUTHORSHIP"
    authority_level: Literal[
        "SELF_ASSERTED", "CORROBORATED_BY_PLATFORM", "THIRD_PARTY_ATTESTED"
    ] = "SELF_ASSERTED"
    evidence_uri: str | None = None


class ClaimRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    work_id: str
    claimant_label: str
    claim_type: str
    state: str
    version: int
    authority_level: str
    superseded_by_id: str | None
    created_at: datetime


class LicenseCreateRequest(BaseModel):
    work_id: str
    claim_id: str | None = None
    permitted_uses: list[str] = Field(default_factory=list)
    prohibited_uses: list[str] = Field(default_factory=list)
    territories: list[str] = Field(default_factory=list)
    channels: list[str] = Field(default_factory=list)
    audiences: list[str] = Field(default_factory=list)
    transformations: list[str] = Field(default_factory=list)
    duties: list[str] = Field(default_factory=list)
    effective_from: datetime | None = None
    effective_until: datetime | None = None
    source_uri: str | None = None


class LicenseRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    work_id: str
    state: str
    version: int
    permitted_uses: list[str]
    prohibited_uses: list[str]
    territories: list[str]
    channels: list[str]
    audiences: list[str]
    transformations: list[str]
    duties: list[str]
    effective_from: datetime | None
    effective_until: datetime | None
    created_at: datetime


class RightsEventRequest(BaseModel):
    event_type: Literal["CORROBORATED", "DISPUTED", "SUPERSEDED", "REVOKED", "EXPIRED"]
    reason: str = Field(min_length=3, max_length=400)
    evidence_uri: str | None = None
    superseded_by_id: str | None = None


class LicenseStateRead(BaseModel):
    id: str
    state: LicenseState


class PolicyCreateRequest(BaseModel):
    policy_key: str = Field(default="default", min_length=1, max_length=120)
    description: str = Field(default="", max_length=400)
    rules: dict = Field(default_factory=dict)


class PolicyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    policy_key: str
    version: int
    description: str
    rules: dict
    block_enabled: bool
    is_default: bool
    digest_sha256: str
    created_at: datetime


class PolicyDryRunRequest(BaseModel):
    scan_id: str
    policy_version_ids: list[str] = Field(default_factory=list, max_length=8)


class PolicyDryRunRead(BaseModel):
    scan_id: str
    recorded_policy_version_id: str | None
    recorded_policy_action: str | None
    evaluations: list[dict]
    note: str = (
        "A dry run never modifies the stored result. Historical evidence keeps the "
        "policy version it was decided under."
    )


# ---------------------------------------------------------------------------
# S16 — reviewer workflow and integrations
# ---------------------------------------------------------------------------


class ReviewCaseRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    scan_id: str
    state: str
    priority: str
    disposition: str
    opened_reason: str
    assignee_principal_id: str | None
    correlation_id: str | None
    created_at: datetime
    resolved_at: datetime | None


class ReviewActionRequest(BaseModel):
    event_type: ReviewEventType
    note: str | None = Field(default=None, max_length=4000)
    assignee_principal_id: str | None = None
    state: ReviewCaseState | None = None
    disposition: ReviewDisposition | None = None


class WebhookEndpointCreateRequest(BaseModel):
    url: HttpUrl
    event_types: list[str] = Field(default_factory=list)


class WebhookEndpointRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    url: str
    event_types: list[str]
    active: bool
    created_at: datetime


class WebhookEndpointCreatedRead(BaseModel):
    endpoint: WebhookEndpointRead
    signing_secret: str
    verification: dict[str, Any]


class WebhookDeliveryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    endpoint_id: str
    event_type: str
    state: str
    attempts: int
    response_status: int | None
    last_error: str | None
    correlation_id: str | None
    created_at: datetime
    delivered_at: datetime | None


class HealthRead(BaseModel):
    status: str
    version: str
    build_signature: str | None = None
    job_backend: str | None = None
    model_bundle_id: str | None = None
    model_bundle_manifest_state: str | None = None
    model_bundle_qualification_state: str | None = None
    model_bundle_manifest_digest: str | None = None
    model_bundle_reason_codes: list[str] = Field(default_factory=list)
    model_bundle_declared_state_verified: bool = False
    model_bundle_demo_ready: bool = False
    model_bundle_runtime_artifact_failures: list[str] = Field(default_factory=list)
    model_bundle_application_revision_matches: bool = False
    model_bundle_runtime_environment_matches: bool = False
    ai_provider: str | None = None
    ai_available: bool = False
    ai_device: str | None = None
    ai_reason: str | None = None
    style_provider: str | None = None
    style_available: bool = False
    style_learned: bool = False
    style_device: str | None = None
    style_reason: str | None = None
    style_profile_manifest_state: str | None = None
    style_profile_manifest_id: str | None = None
    style_profile_count: int = 0
    style_authorized_profile_count: int = 0
    synthetic_provider: str | None = None
    synthetic_available: bool = False
    synthetic_detectors: list[str] = Field(default_factory=list)
    synthetic_evidence_families: list[str] = Field(default_factory=list)
    synthetic_batched_detectors: list[str] = Field(default_factory=list)
    synthetic_reason: str | None = None
    synthetic_calibration_state: str | None = None
    synthetic_routing: dict[str, Any] | None = None
    synthetic_primary_provider: str | None = None
    synthetic_primary_state: str | None = None
    synthetic_local_fallback_available: bool = False
    visible_marker_provider: str | None = None
    visible_marker_available: bool = False
    visible_marker_reason: str | None = None
    provenance_provider: str | None = None
    provenance_available: bool = False
    provenance_trust_policy_id: str | None = None
    proof_provider: str | None = None
    proof_available: bool = False
    proof_scope: str | None = None
    origin_policy_mode: str | None = None
    copy_retrieval_requirement: str | None = None
    copy_exhaustive_verification_max_entries: int = 0
    # v0.9.3 platform readiness. Additive so existing clients keep working.
    proof_network_label: str | None = None
    proof_chain_id: int | None = None
    proof_contract_address: str | None = None
    proof_schema_uid: str | None = None
    proof_attester_address: str | None = None
    proof_requires_chain: bool = False
    blockchain_deployment_id: str | None = None
    blockchain_anchor_states: dict[str, int] = Field(default_factory=dict)
    blockchain_oldest_pending_at: str | None = None
    signing_enabled: bool = False
    signing_kid: str | None = None
    signing_algorithm: str | None = None
    signing_key_source: str | None = None
    transparency_log_id: str | None = None
    transparency_tree_size: int | None = None
    queue_transport: str | None = None
    queue_depth: int | None = None
    queue_pending: int | None = None
    queue_dead_letter: int | None = None
    outbox_pending: int | None = None
    storage_provider: str | None = None
    dev_auth_enabled: bool = False
    degraded_capabilities: list[str] = Field(default_factory=list)
