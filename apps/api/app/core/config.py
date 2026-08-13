from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.domain.enums import CopyRetrievalRequirement, OriginPolicyMode


class Settings(BaseSettings):
    app_name: str = "CreatorProof API"
    environment: Literal["development", "test", "production"] = "development"
    database_url: str = "sqlite:///./creatorproof.db"
    storage_root: Path = Path("./data")
    job_backend: Literal["inline", "local", "redis"] = "local"
    local_job_workers: int = Field(default=1, ge=1, le=4)
    redis_url: str = "redis://localhost:6379/0"
    redis_queue_name: str = "creatorproof:scans"
    dev_api_key: str = Field(default="change-me-before-sharing", min_length=8)
    dev_tenant_id: str = "tn_demo"
    dev_tenant_slug: str = "demo"
    max_upload_bytes: int = 12 * 1024 * 1024
    max_image_pixels: int = 40_000_000
    retrieval_top_k: int = 8
    copy_retrieval_requirement: CopyRetrievalRequirement = CopyRetrievalRequirement.LEARNED_REQUIRED
    candidate_retention_seconds: int = 0
    sscd_model_path: Path = Path("./models/sscd_disc_mixup.torchscript.pt")
    sscd_device: Literal["auto", "cpu", "cuda"] = "auto"
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

    # v0.9 synthetic-origin evidence. Detection is deliberately independent from
    # copy and style evidence: a score can route a case to review but cannot prove
    # that an image is human-made, identify training data, or establish infringement.
    synthetic_detector: Literal["auto", "community", "torchscript", "off"] = "auto"
    synthetic_community_model_path: Path = Path("./models/community-forensics-384")
    synthetic_torchscript_model_path: Path = Path("./models/synthetic-detector.torchscript.pt")
    synthetic_device: Literal["auto", "cpu", "cuda"] = "auto"
    synthetic_external_detectors_json: str = "[]"
    synthetic_calibration_path: Path = Path("./models/synthetic-calibration.json")
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
    c2pa_timeout_seconds: int = 20

    # Proof anchoring has two explicit levels. The local Merkle log is an auditable
    # transparency receipt, not a blockchain. EAS mode submits only a bytes32 packet
    # commitment to a configured EVM network and returns the mined transaction receipt.
    proof_anchor_mode: Literal["auto", "none", "merkle", "eas"] = "auto"
    proof_log_path: Path = Path("./data/proof-log.jsonl")
    eas_rpc_url: str = ""
    eas_contract_address: str = ""
    eas_schema_uid: str = ""
    eas_private_key: str = ""
    eas_recipient: str = "0x0000000000000000000000000000000000000000"
    eas_explorer_tx_base_url: str = ""
    eas_chain_id: int | None = None
    eas_receipt_timeout_seconds: int = 90

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


@lru_cache
def get_settings() -> Settings:
    return Settings()
