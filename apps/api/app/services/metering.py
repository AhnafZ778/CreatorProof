"""Usage metering for plan limits and unit economics (S17).

Metering must never break the operation it measures. A failure to record a meter
is logged and swallowed, exactly like the audit trail: billing data is valuable,
but silently turning a successful scan into a 500 because a counter could not be
written would be a far worse trade.

Meters are recorded as append-only rows so a pilot invoice can be reconstructed
and disputed against the same evidence the customer already has.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.observability import METRICS, log_event

logger = logging.getLogger("creatorproof.metering")


class Meter:
    """Stable meter names. These appear on invoices, so they never change."""

    SCAN = "scan"
    PROTECTED_ASSET = "protected_asset"
    STORAGE_BYTES = "storage_bytes"
    GPU_STAGE_SECONDS = "gpu_stage_seconds"
    PROOF_ANCHOR = "proof_anchor"
    RETENTION_TIER = "retention_tier"


ALL_METERS = (
    Meter.SCAN,
    Meter.PROTECTED_ASSET,
    Meter.STORAGE_BYTES,
    Meter.GPU_STAGE_SECONDS,
    Meter.PROOF_ANCHOR,
    Meter.RETENTION_TIER,
)


def retention_tier(seconds: int) -> str:
    """Classify a retention configuration into a billable tier.

    Retention drives storage cost, so it is metered as a tier rather than a raw
    duration: a pilot invoice needs a stable label, not a config value that may
    be tuned mid-month.
    """

    if seconds <= 0:
        return "none"
    if seconds <= 24 * 3600:
        return "short"
    if seconds <= 30 * 24 * 3600:
        return "standard"
    return "extended"


_ACCELERATED_PROVIDERS = ("ai_retrieval", "style_retrieval", "synthetic_detection")


def gpu_providers_in_use(container) -> list[str]:
    """Names of providers currently resolved onto a CUDA device.

    Providers report their device only once a model is actually loaded, and some
    are routers that may not expose one at all, so every lookup is defensive: a
    missing attribute means "not accelerated", never an error during a scan.
    """

    active: list[str] = []
    for name in _ACCELERATED_PROVIDERS:
        provider = getattr(container, name, None)
        if provider is None:
            continue
        try:
            device = getattr(provider, "device", None)
        except Exception:
            continue
        if isinstance(device, str) and device.startswith("cuda"):
            active.append(name)
    return active


def record_usage(
    db: Session,
    *,
    tenant_id: str | None,
    meter: str,
    quantity: int = 1,
    scan_id: str | None = None,
    attributes: dict | None = None,
    commit: bool = True,
) -> None:
    """Append one metered unit. Never raises."""

    if not tenant_id or quantity <= 0:
        return

    from app.models import UsageRecord

    try:
        db.add(
            UsageRecord(
                tenant_id=tenant_id,
                meter=meter,
                quantity=int(quantity),
                scan_id=scan_id,
                attributes=attributes or {},
            )
        )
        if commit:
            db.commit()
        METRICS.increment("creatorproof_usage_recorded_total", float(quantity), meter=meter)
    except Exception:
        db.rollback()
        # Logged rather than raised: see the module docstring.
        logger.warning("usage_record_persist_failed meter=%s tenant_id=%s", meter, tenant_id)
        return

    log_event(logger, "usage_recorded", meter=meter, tenant_id=tenant_id, quantity=quantity)


def usage_since(
    db: Session,
    *,
    tenant_id: str,
    meter: str,
    since: datetime,
) -> int:
    """Total quantity for one meter since a point in time."""

    from app.models import UsageRecord

    total = db.scalar(
        select(func.coalesce(func.sum(UsageRecord.quantity), 0)).where(
            UsageRecord.tenant_id == tenant_id,
            UsageRecord.meter == meter,
            UsageRecord.created_at >= since,
        )
    )
    return int(total or 0)


@dataclass(frozen=True)
class UsageWindow:
    """Aggregated usage for a tenant over a window, for the cost dashboard."""

    tenant_id: str
    window_days: int
    window_start: datetime
    window_end: datetime
    totals: dict[str, int]

    def as_dict(self) -> dict:
        return {
            "tenant_id": self.tenant_id,
            "window_days": self.window_days,
            "window_start": self.window_start.isoformat(),
            "window_end": self.window_end.isoformat(),
            "totals": dict(self.totals),
        }


def summarize_usage(
    db: Session,
    *,
    tenant_id: str,
    window_days: int = 30,
    meters: Iterable[str] = ALL_METERS,
) -> UsageWindow:
    """Aggregate every meter for a tenant over a trailing window.

    Meters with no activity are reported as zero rather than omitted, so a
    dashboard cannot mistake "not measured" for "nothing used".
    """

    from app.models import UsageRecord

    end = datetime.now(UTC)
    start = end - timedelta(days=window_days)
    requested = list(meters)

    rows = db.execute(
        select(UsageRecord.meter, func.coalesce(func.sum(UsageRecord.quantity), 0))
        .where(
            UsageRecord.tenant_id == tenant_id,
            UsageRecord.created_at >= start,
            UsageRecord.meter.in_(requested),
        )
        .group_by(UsageRecord.meter)
    ).all()

    totals = {meter: 0 for meter in requested}
    for meter, quantity in rows:
        totals[str(meter)] = int(quantity or 0)

    return UsageWindow(
        tenant_id=tenant_id,
        window_days=window_days,
        window_start=start,
        window_end=end,
        totals=totals,
    )
