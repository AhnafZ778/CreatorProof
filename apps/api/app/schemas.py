from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import CapabilityExecutionState, CoverageReasonCode, CoverageStatus


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
    created_at: datetime


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
    evidence_packet: EvidencePacketRead | None
    error_code: str | None
    created_at: datetime
    completed_at: datetime | None


class HealthRead(BaseModel):
    status: str
    version: str
    build_signature: str | None = None
    job_backend: str | None = None
    ai_provider: str | None = None
    ai_available: bool = False
    ai_device: str | None = None
    ai_reason: str | None = None
    style_provider: str | None = None
    style_available: bool = False
    style_learned: bool = False
    style_device: str | None = None
    style_reason: str | None = None
    synthetic_provider: str | None = None
    synthetic_available: bool = False
    synthetic_detectors: list[str] = Field(default_factory=list)
    synthetic_evidence_families: list[str] = Field(default_factory=list)
    synthetic_batched_detectors: list[str] = Field(default_factory=list)
    synthetic_reason: str | None = None
    visible_marker_provider: str | None = None
    visible_marker_available: bool = False
    visible_marker_reason: str | None = None
    provenance_provider: str | None = None
    provenance_available: bool = False
    proof_provider: str | None = None
    proof_available: bool = False
    proof_scope: str | None = None
    origin_policy_mode: str | None = None
    copy_retrieval_requirement: str | None = None
