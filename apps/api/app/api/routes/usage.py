"""Usage and unit-economics reporting (S17).

Usage is reported per tenant and is always scoped to the caller's own tenant, so
this endpoint can be exposed to a pilot customer without leaking another
organization's volumes. It reports metered units only; it deliberately does not
invent prices, because a support promise must be priced from measured
infrastructure rather than a hard-coded rate card.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_container, get_db, require_scope
from app.container import Container
from app.core.security import AuthContext
from app.domain.platform import CredentialScope
from app.services.metering import retention_tier, summarize_usage

router = APIRouter(prefix="/v1/usage", tags=["usage"])


@router.get("")
def read_usage(
    auth: Annotated[AuthContext, Depends(require_scope(CredentialScope.SCANS_READ))],
    container: Annotated[Container, Depends(get_container)],
    db: Annotated[Session, Depends(get_db)],
    window_days: Annotated[int, Query(ge=1, le=365)] = 30,
) -> dict:
    summary = summarize_usage(db, tenant_id=auth.tenant_id, window_days=window_days)
    quota = container.settings.tenant_scan_quota_per_day
    return {
        **summary.as_dict(),
        "plan": {
            "scan_quota_per_day": quota,
            "scan_quota_enforced": quota > 0,
            "retention_tier": retention_tier(container.settings.candidate_retention_seconds),
        },
        "notes": [
            "Quantities are metered units, not prices.",
            "storage_bytes counts registered reference bytes at upload time.",
            "gpu_stage_seconds is zero when models run on CPU.",
        ],
    }
