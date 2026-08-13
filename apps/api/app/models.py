from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.domain.enums import AnchorStatus, ClaimState, RightsPath, ScanState
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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class Scan(Base):
    __tablename__ = "scans"
    __table_args__ = (
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

    @property
    def request_digest(self) -> str:
        return scan_request_digest(
            candidate_sha256=self.candidate_sha256,
            catalog_id=self.catalog_id,
            intended_use=self.intended_use,
        )
