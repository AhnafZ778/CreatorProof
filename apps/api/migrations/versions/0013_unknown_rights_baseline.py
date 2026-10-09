"""Give existing active works an explicit UNKNOWN rights version when absent.

This records missing instructions, never inferred historical consent or rights.
Existing policies and deleted works are preserved. The frozen projection matches
the Phase 1 rights-policy digest contract without depending on evolving payload
defaults or producing a fictitious signed registration event.
"""

import hashlib
import json
from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision: str = "0013_unknown_rights_baseline"
down_revision: str | None = "0012_sqlite_database_immutability"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PERMISSION_FIELDS = (
    "search_indexing_permission",
    "commercial_search_permission",
    "AI_training_permission",
    "noncommercial_training_permission",
    "commercial_training_permission",
    "fine_tuning_permission",
    "style_reference_permission",
    "image_to_image_permission",
    "image_editing_permission",
    "derivative_generation_permission",
    "likeness_use_permission",
)
_DIMENSIONS = {
    "asset_path": None,
    "attribution_required": None,
    "attribution_text": None,
    "audiences": [],
    "channels": [],
    "geographic_scope": [],
    "license_contact": None,
    "license_fee_currency": None,
    "license_required": None,
    "minimum_license_fee": None,
    "permitted_models": [],
    "permitted_platforms": [],
    "policy_notes": None,
    "prohibited_models": [],
    "prohibited_platforms": [],
    "tdm_reservation": None,
    "transformations": [],
}


def upgrade() -> None:
    connection = op.get_bind()
    previous_override = None
    if connection.dialect.name == "postgresql":
        previous_override = connection.execute(
            sa.text("SELECT current_setting('app.bypass_rls', true)")
        ).scalar_one()
        connection.execute(sa.text("SELECT set_config('app.bypass_rls', 'on', true)"))
    metadata = sa.MetaData()
    works = sa.Table("works", metadata, autoload_with=connection)
    policies = sa.Table("rights_policy_versions", metadata, autoload_with=connection)
    unrecorded = connection.execute(
        sa.select(works.c.id, works.c.tenant_id, works.c.created_at)
        .where(works.c.deleted_at.is_(None))
        .where(
            ~sa.exists().where(
                policies.c.tenant_id == works.c.tenant_id,
                policies.c.work_id == works.c.id,
            )
        )
    ).all()
    for work in unrecorded:
        registered_at = work.created_at
        registered_at = (
            registered_at.astimezone(UTC)
            if registered_at.tzinfo
            else registered_at.replace(tzinfo=UTC)
        )
        projection = {
            "schema": "creatorproof.rights-policy.v1",
            "work_id": work.id,
            "version": 1,
            "permissions": {field: "UNKNOWN" for field in _PERMISSION_FIELDS},
            "dimensions": _DIMENSIONS,
            "creator_assertions": {
                "assertion": {},
                "baseline_source": "SYSTEM_REGISTRATION_UNKNOWN",
                "creator_id": None,
                "status": "UNKNOWN",
            },
            "consent_metadata": {
                "assertion": {},
                "source": None,
                "status": "UNKNOWN",
                "timestamp": None,
            },
            "revocation_metadata": {"status": "UNKNOWN", "timestamp": None},
            "corroboration": [],
            "effective_from": registered_at.isoformat(),
            "effective_until": None,
        }
        # This frozen projection contains ASCII keys, strings, integer 1 and
        # nulls only: compact sorted JSON is identical to the JCS serializer.
        digest = hashlib.sha256(
            json.dumps(
                projection, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            ).encode("utf-8")
        ).hexdigest()
        identity = hashlib.sha256(f"{work.tenant_id}\0{work.id}".encode()).hexdigest()[:40]
        connection.execute(
            policies.insert().values(
                id=f"rpol_baseline_{identity}",
                tenant_id=work.tenant_id,
                work_id=work.id,
                version=1,
                permissions=projection["permissions"],
                dimensions=projection["dimensions"],
                creator_assertions=projection["creator_assertions"],
                consent_metadata=projection["consent_metadata"],
                revocation_metadata=projection["revocation_metadata"],
                corroboration=[],
                effective_from=registered_at,
                effective_until=None,
                superseded_by_id=None,
                digest_sha256=digest,
                created_by_principal_id=None,
                created_at=datetime.now(UTC),
            )
        )
    if connection.dialect.name == "postgresql":
        connection.execute(
            sa.text("SELECT set_config('app.bypass_rls', :previous, true)"),
            {"previous": previous_override or ""},
        )


def downgrade() -> None:
    raise RuntimeError("Rights history is append-only; restore a verified backup to roll back")
