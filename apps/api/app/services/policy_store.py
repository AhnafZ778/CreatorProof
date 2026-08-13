"""Versioned rights and policy evaluation.

Two invariants shape this module:

1. A revoked, disputed, superseded or expired claim or license can never
   authorize a use. Policy configuration cannot switch that off.
2. Changing a policy never rewrites history. Evidence keeps the policy version
   it was decided under; a new version only affects new evaluations and dry runs.

Creator-profile resemblance stays advisory here as well: it can raise review, it
can never by itself authorize or block.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.enums import ClaimState, CoverageStatus, MatchStatus, PolicyAction, RightsPath
from app.domain.platform import LicenseState
from app.services.canonical import canonical_digest

logger = logging.getLogger("creatorproof.policy")

DEFAULT_POLICY_KEY = "default"

# Terminal claim/license states. Listed explicitly so a future state addition is a
# compile-time visible decision rather than a silent authorization.
UNAUTHORIZING_CLAIM_STATES = frozenset(
    {ClaimState.DISPUTED, ClaimState.SUPERSEDED, ClaimState.REVOKED}
)
UNAUTHORIZING_LICENSE_STATES = frozenset(
    {
        LicenseState.EXPIRED,
        LicenseState.SUSPENDED,
        LicenseState.REVOKED,
        LicenseState.SUPERSEDED,
    }
)

DEFAULT_POLICY_RULES: dict = {
    "schema": "creatorproof.policy.v1",
    "description": "Conservative default: only a corroborated, in-scope permission may pass.",
    "fail_closed": True,
    "require_complete_coverage_for_pass": True,
    "require_corroborated_claim_for_pass": True,
    "block_enabled": False,
    "escalate_on": {
        "ai_origin_classification": [],
        "creator_profile_tier": [],
    },
    "review_on_missing_facts": True,
    # The capability mode is bound when the scan is accepted. This persisted
    # rule decides whether a REQUIRED request is allowed to affect the decision.
    "honor_required_origin_policy_mode": True,
    "scope_dimensions": ["territory", "channel", "audience", "transformation"],
}


def ensure_default_policy(
    db: Session,
    *,
    tenant_id: str,
    signer=None,
    transparency=None,
    blockchain=None,
):
    """Seed and, when integrity dependencies are supplied, attest the default policy.

    Policy rows remain the executable source of truth in PostgreSQL. The signed
    integrity event commits the immutable row's digest into the transparency log;
    only a checkpoint root is eligible for public-chain anchoring.
    """
    from app.models import IntegrityEvent, PolicyVersion

    existing = db.scalar(
        select(PolicyVersion).where(
            PolicyVersion.tenant_id == tenant_id,
            PolicyVersion.policy_key == DEFAULT_POLICY_KEY,
        )
    )
    created = existing is None
    row = existing
    if row is None:
        row = PolicyStore().create_version(
            db,
            tenant_id=tenant_id,
            policy_key=DEFAULT_POLICY_KEY,
            description=str(DEFAULT_POLICY_RULES["description"]),
            rules=DEFAULT_POLICY_RULES,
            is_default=True,
            commit=False,
        )

    if signer is None or transparency is None:
        db.commit()
        return row

    from app.services.blockchain import append_integrity_event, prepare_integrity_event

    integrity_event = db.scalar(
        select(IntegrityEvent).where(
            IntegrityEvent.tenant_id == tenant_id,
            IntegrityEvent.subject_type == "policy_version",
            IntegrityEvent.subject_id == row.id,
            IntegrityEvent.event_type.in_(
                ["POLICY_VERSION_CREATED", "POLICY_VERSION_SEED_ATTESTED"]
            ),
        )
    )
    if integrity_event is None:
        integrity_event = prepare_integrity_event(
            db,
            signer=signer,
            tenant_id=tenant_id,
            event_type=("POLICY_VERSION_CREATED" if created else "POLICY_VERSION_SEED_ATTESTED"),
            subject_type="policy_version",
            subject_id=row.id,
            attributes={
                "policy_key": row.policy_key,
                "version": row.version,
                "policy_digest_sha256": row.digest_sha256,
                "description_sha256": hashlib.sha256(row.description.encode()).hexdigest(),
                "block_enabled": row.block_enabled,
                "is_default": row.is_default,
                "seed_attestation": not created,
            },
        )
        db.commit()
    elif created:
        db.commit()

    try:
        append_integrity_event(
            db,
            event=integrity_event,
            transparency=transparency,
            blockchain=blockchain,
        )
    except Exception:
        # The signed event is durable. The integrity-event recovery dispatcher
        # will append it after a transient log or RPC failure.
        logger.exception("default_policy_integrity_publish_deferred policy_version_id=%s", row.id)
    return row


class PolicyStore:
    def create_version(
        self,
        db: Session,
        *,
        tenant_id: str,
        policy_key: str,
        description: str,
        rules: dict,
        is_default: bool = False,
        commit: bool = True,
    ):
        from app.models import PolicyVersion

        latest = db.scalar(
            select(PolicyVersion)
            .where(
                PolicyVersion.tenant_id == tenant_id,
                PolicyVersion.policy_key == policy_key,
            )
            .order_by(PolicyVersion.version.desc())
            .limit(1)
        )
        next_version = (latest.version + 1) if latest is not None else 1
        merged = {**DEFAULT_POLICY_RULES, **(rules or {})}
        row = PolicyVersion(
            tenant_id=tenant_id,
            policy_key=policy_key,
            version=next_version,
            description=description,
            rules=merged,
            block_enabled=bool(merged.get("block_enabled", False)),
            is_default=is_default,
            digest_sha256=canonical_digest(
                {"policy_key": policy_key, "version": next_version, "rules": merged}
            ),
        )
        db.add(row)
        if commit:
            db.commit()
        else:
            db.flush()
        return row

    def get_active(self, db: Session, *, tenant_id: str, policy_key: str = DEFAULT_POLICY_KEY):
        from app.models import PolicyVersion

        return db.scalar(
            select(PolicyVersion)
            .where(
                PolicyVersion.tenant_id == tenant_id,
                PolicyVersion.policy_key == policy_key,
            )
            .order_by(PolicyVersion.version.desc())
            .limit(1)
        )

    def get_by_id(self, db: Session, *, tenant_id: str, policy_version_id: str):
        from app.models import PolicyVersion

        return db.scalar(
            select(PolicyVersion).where(
                PolicyVersion.tenant_id == tenant_id, PolicyVersion.id == policy_version_id
            )
        )

    def list_versions(self, db: Session, *, tenant_id: str):
        from app.models import PolicyVersion

        return db.scalars(
            select(PolicyVersion)
            .where(PolicyVersion.tenant_id == tenant_id)
            .order_by(PolicyVersion.policy_key, PolicyVersion.version.desc())
        ).all()


def _license_authorizes(license_row, *, intended_use: str, now: datetime) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    state = str(license_row.state)
    if state in {str(item) for item in UNAUTHORIZING_LICENSE_STATES}:
        return False, [f"LICENSE_{state}"]
    if license_row.effective_from and _as_utc(license_row.effective_from) > now:
        return False, ["LICENSE_NOT_YET_EFFECTIVE"]
    if license_row.effective_until and _as_utc(license_row.effective_until) <= now:
        return False, ["LICENSE_EXPIRED"]
    if intended_use in (license_row.prohibited_uses or []):
        return False, ["LICENSE_PROHIBITS_INTENDED_USE"]
    if intended_use not in (license_row.permitted_uses or []):
        reasons.append("LICENSE_DOES_NOT_LIST_INTENDED_USE")
        return False, reasons
    return True, ["LICENSE_PERMITS_INTENDED_USE"]


def _sha256_optional(value: str | None) -> str | None:
    return hashlib.sha256(value.encode()).hexdigest() if value else None


def _integrity_datetime(value: datetime | None) -> str | None:
    return _as_utc(value).astimezone(UTC).isoformat() if value is not None else None


def claim_integrity_projection(claim) -> dict:
    """Privacy-preserving canonical projection committed by every claim event."""
    return {
        "work_id": claim.work_id,
        "claimant_party_id": claim.claimant_party_id,
        "claimant_label_sha256": _sha256_optional(claim.claimant_label),
        "claim_type": claim.claim_type,
        "state": str(claim.state),
        "version": int(claim.version),
        "authority_level": claim.authority_level,
        "evidence_uri_sha256": _sha256_optional(claim.evidence_uri),
        "superseded_by_id": claim.superseded_by_id,
        "effective_from": _integrity_datetime(claim.effective_from),
        "effective_until": _integrity_datetime(claim.effective_until),
    }


def license_integrity_projection(license_row) -> dict:
    """Canonical permission projection committed by every license event."""
    return {
        "work_id": license_row.work_id,
        "claim_id": license_row.claim_id,
        "grantor_party_id": license_row.grantor_party_id,
        "version": int(license_row.version),
        "state": str(license_row.state),
        "permitted_uses": list(license_row.permitted_uses or []),
        "prohibited_uses": list(license_row.prohibited_uses or []),
        "territories": list(license_row.territories or []),
        "channels": list(license_row.channels or []),
        "audiences": list(license_row.audiences or []),
        "transformations": list(license_row.transformations or []),
        "duties": list(license_row.duties or []),
        "effective_from": _integrity_datetime(license_row.effective_from),
        "effective_until": _integrity_datetime(license_row.effective_until),
        "superseded_by_id": license_row.superseded_by_id,
        "source_uri_sha256": _sha256_optional(license_row.source_uri),
    }


def _rights_projection_integrity(
    db: Session,
    *,
    tenant_id: str,
    claims: list,
    licenses: list,
) -> dict[tuple[str, str], dict]:
    """Verify projections against signed, logged immutable events in one batch.

    A database row is convenient current state, not independent authority. A row
    may contribute to authorization only when its complete canonical projection
    matches the latest valid state event and that event is present in the
    append-only transparency log.
    """
    from app.models import IntegrityEvent, SigningKey, TransparencyLeaf
    from app.services.signing import verify_statement_signature

    subject_ids = [row.id for row in [*claims, *licenses]]
    if not subject_ids:
        return {}
    allowed_event_types = {
        "claim": {"CLAIM_CREATED", "CLAIM_STATE_CHANGED"},
        "license": {"LICENSE_CREATED", "LICENSE_STATE_CHANGED"},
    }
    events = db.scalars(
        select(IntegrityEvent)
        .where(
            IntegrityEvent.tenant_id == tenant_id,
            IntegrityEvent.subject_id.in_(subject_ids),
            IntegrityEvent.subject_type.in_(["claim", "license"]),
            IntegrityEvent.event_type.in_(
                [
                    "CLAIM_CREATED",
                    "CLAIM_STATE_CHANGED",
                    "LICENSE_CREATED",
                    "LICENSE_STATE_CHANGED",
                ]
            ),
        )
        .order_by(IntegrityEvent.created_at, IntegrityEvent.id)
    ).all()
    latest: dict[tuple[str, str], object] = {}
    for event in events:
        latest[(event.subject_type, event.subject_id)] = event

    kids = {event.signature_kid for event in latest.values() if event.signature_kid}
    keys = {
        key.kid: key
        for key in (
            db.scalars(select(SigningKey).where(SigningKey.kid.in_(kids))).all() if kids else []
        )
    }
    event_ids = [event.id for event in latest.values()]
    leaves = {
        leaf.statement_id: leaf
        for leaf in db.scalars(
            select(TransparencyLeaf).where(TransparencyLeaf.statement_id.in_(event_ids))
        ).all()
    }

    results: dict[tuple[str, str], dict] = {}
    for subject_type, rows in (("claim", claims), ("license", licenses)):
        for row in rows:
            key = (subject_type, row.id)
            event = latest.get(key)
            result = {
                "verified": False,
                "reason_code": f"{subject_type.upper()}_INTEGRITY_EVENT_MISSING",
                "event_id": event.id if event is not None else None,
                "event_digest_sha256": (event.payload_digest_sha256 if event is not None else None),
            }
            if event is None:
                results[key] = result
                continue
            payload = event.payload if isinstance(event.payload, dict) else {}
            attributes = payload.get("attributes") if isinstance(payload, dict) else None
            signing_key = keys.get(event.signature_kid)
            leaf = leaves.get(event.id)
            projection = (
                claim_integrity_projection(row)
                if subject_type == "claim"
                else license_integrity_projection(row)
            )
            expected_projection_digest = canonical_digest(projection)
            reason = None
            if event.event_type not in allowed_event_types[subject_type]:
                reason = f"{subject_type.upper()}_INTEGRITY_EVENT_TYPE_INVALID"
            elif payload.get("tenant_id") != tenant_id:
                reason = f"{subject_type.upper()}_INTEGRITY_TENANT_MISMATCH"
            elif payload.get("subject_type") != subject_type or payload.get("subject_id") != row.id:
                reason = f"{subject_type.upper()}_INTEGRITY_SUBJECT_MISMATCH"
            elif canonical_digest(payload) != event.payload_digest_sha256:
                reason = f"{subject_type.upper()}_INTEGRITY_DIGEST_MISMATCH"
            elif signing_key is None or not verify_statement_signature(
                payload,
                signature_b64=event.signature_b64,
                public_key_hex=signing_key.public_key_hex,
            ):
                reason = f"{subject_type.upper()}_INTEGRITY_SIGNATURE_INVALID"
            elif leaf is None or leaf.packet_hash_sha256 != event.payload_digest_sha256:
                reason = f"{subject_type.upper()}_INTEGRITY_LOG_INCLUSION_MISSING"
            elif not isinstance(attributes, dict):
                reason = f"{subject_type.upper()}_INTEGRITY_PROJECTION_MISSING"
            elif attributes.get("projection_digest_sha256") != expected_projection_digest:
                reason = f"{subject_type.upper()}_PROJECTION_INTEGRITY_MISMATCH"
            elif attributes.get("projection") != projection:
                reason = f"{subject_type.upper()}_PROJECTION_INTEGRITY_MISMATCH"
            if reason is None:
                result.update(
                    {
                        "verified": True,
                        "reason_code": None,
                        "projection_digest_sha256": expected_projection_digest,
                    }
                )
            else:
                result["reason_code"] = reason
            results[key] = result
    return results


def collect_rights_facts(
    db: Session,
    *,
    tenant_id: str,
    work_id: str | None,
    intended_use: str,
) -> dict:
    """Snapshot the persisted rights position for one work and intended use.

    Denormalized ``Work.rights_path``, ``Work.allowed_uses`` and
    ``Work.claim_state`` fields are intentionally not read here. They remain a
    compatibility projection; only Claim and License rows can authorize a live
    scan.
    """
    from app.models import Claim, License

    if work_id is None:
        facts = {
            "schema": "creatorproof.rights_facts.v1",
            "source": "PERSISTED_CLAIM_AND_LICENSE_ROWS",
            "work_id": None,
            "claims": [],
            "licenses": [],
            "authorizing_license_id": None,
            "scope_authorizing_license_ids": [],
            "derived_rights_path": str(RightsPath.NO_LICENSE_INFO),
            "authorized": False,
            "blocking_reason_codes": [],
            "missing_facts": ["NO_MATCHED_WORK"],
        }
        return {**facts, "snapshot_digest_sha256": canonical_digest(facts)}

    now = datetime.now(UTC)
    claims = db.scalars(
        select(Claim)
        .where(Claim.tenant_id == tenant_id, Claim.work_id == work_id)
        .order_by(Claim.created_at, Claim.id)
    ).all()
    licenses = db.scalars(
        select(License)
        .where(License.tenant_id == tenant_id, License.work_id == work_id)
        .order_by(License.version, License.created_at, License.id)
    ).all()
    projection_integrity = _rights_projection_integrity(
        db,
        tenant_id=tenant_id,
        claims=list(claims),
        licenses=list(licenses),
    )

    claim_by_id = {claim.id: claim for claim in claims}
    blocking: list[str] = []
    missing: list[str] = []
    claim_reasons: list[str] = []
    corroborated = []
    for claim in claims:
        integrity = projection_integrity.get(("claim", claim.id)) or {
            "verified": False,
            "reason_code": "CLAIM_INTEGRITY_EVENT_MISSING",
        }
        state = str(claim.state)
        effective = True
        if not integrity["verified"]:
            effective = False
            claim_reasons.append(str(integrity["reason_code"]))
            missing.append("CLAIM_PROJECTION_INTEGRITY_UNVERIFIED")
        if claim.effective_from and _as_utc(claim.effective_from) > now:
            effective = False
            claim_reasons.append("CLAIM_NOT_YET_EFFECTIVE")
        if claim.effective_until and _as_utc(claim.effective_until) <= now:
            effective = False
            claim_reasons.append("CLAIM_NO_LONGER_EFFECTIVE")
        if state in {str(item) for item in UNAUTHORIZING_CLAIM_STATES}:
            effective = False
            claim_reasons.append(f"CLAIM_{state}")
        if state == str(ClaimState.DISPUTED):
            blocking.append("CLAIM_DISPUTED")
        if state == str(ClaimState.CORROBORATED) and effective:
            corroborated.append(claim)
    if not claims:
        missing.append("NO_RECORDED_CLAIM")
    elif not corroborated:
        missing.append("NO_CORROBORATED_CLAIM")

    scope_authorizing_license_ids: list[str] = []
    strongly_authorizing_license_ids: list[str] = []
    license_reasons: list[str] = []
    for license_row in licenses:
        integrity = projection_integrity.get(("license", license_row.id)) or {
            "verified": False,
            "reason_code": "LICENSE_INTEGRITY_EVENT_MISSING",
        }
        if not integrity["verified"]:
            license_reasons.append(str(integrity["reason_code"]))
            missing.append("LICENSE_PROJECTION_INTEGRITY_UNVERIFIED")
            continue
        authorized, reasons = _license_authorizes(license_row, intended_use=intended_use, now=now)
        license_reasons.extend(reasons)
        if str(license_row.state) == str(LicenseState.SUSPENDED):
            blocking.append("LICENSE_SUSPENDED")
        if not authorized:
            continue
        scope_authorizing_license_ids.append(license_row.id)
        backing_claim = claim_by_id.get(license_row.claim_id)
        if backing_claim is None:
            license_reasons.append("LICENSE_NOT_BOUND_TO_RECORDED_CLAIM")
        elif backing_claim in corroborated:
            strongly_authorizing_license_ids.append(license_row.id)
        else:
            license_reasons.append("LICENSE_BACKING_CLAIM_NOT_CORROBORATED")
            reason_by_state = {
                str(ClaimState.ASSERTED): "MATCHED_CLAIM_NOT_CORROBORATED",
                str(ClaimState.DISPUTED): "MATCHED_CLAIM_DISPUTED",
                str(ClaimState.SUPERSEDED): "MATCHED_CLAIM_SUPERSEDED",
                str(ClaimState.REVOKED): "MATCHED_CLAIM_REVOKED",
            }
            license_reasons.append(
                reason_by_state.get(str(backing_claim.state), "MATCHED_CLAIM_NOT_CORROBORATED")
            )
    if not licenses:
        missing.append("NO_RECORDED_LICENSE")

    authorizing_license_id = (
        strongly_authorizing_license_ids[0] if strongly_authorizing_license_ids else None
    )
    if authorizing_license_id is not None:
        derived_rights_path = RightsPath.EXISTING_LICENSE
    elif blocking:
        derived_rights_path = RightsPath.DISPUTED
    elif licenses:
        derived_rights_path = RightsPath.EXISTING_LICENSE
    else:
        derived_rights_path = RightsPath.NO_LICENSE_INFO

    facts = {
        "schema": "creatorproof.rights_facts.v1",
        "source": "PERSISTED_CLAIM_AND_LICENSE_ROWS",
        "work_id": work_id,
        "claims": [
            {
                "id": claim.id,
                "state": claim.state,
                "claim_type": claim.claim_type,
                "authority_level": claim.authority_level,
                "version": claim.version,
                "effective_from": (
                    _as_utc(claim.effective_from).isoformat() if claim.effective_from else None
                ),
                "effective_until": (
                    _as_utc(claim.effective_until).isoformat() if claim.effective_until else None
                ),
                "integrity": projection_integrity.get(("claim", claim.id)),
            }
            for claim in claims
        ],
        "licenses": [
            {
                "id": row.id,
                "state": row.state,
                "version": row.version,
                "permitted_uses": list(row.permitted_uses or []),
                "prohibited_uses": list(row.prohibited_uses or []),
                "claim_id": row.claim_id,
                "effective_from": (
                    _as_utc(row.effective_from).isoformat() if row.effective_from else None
                ),
                "effective_until": (
                    _as_utc(row.effective_until).isoformat() if row.effective_until else None
                ),
                "integrity": projection_integrity.get(("license", row.id)),
            }
            for row in licenses
        ],
        "authorizing_license_id": authorizing_license_id,
        "scope_authorizing_license_ids": scope_authorizing_license_ids,
        "strongly_authorizing_license_ids": strongly_authorizing_license_ids,
        "derived_rights_path": str(derived_rights_path),
        "authorized": authorizing_license_id is not None,
        "claim_reason_codes": sorted(set(claim_reasons)),
        "license_reason_codes": sorted(set(license_reasons)),
        "blocking_reason_codes": sorted(set(blocking)),
        "missing_facts": sorted(set(missing)),
        "integrity_enforcement": "SIGNED_EVENT_AND_TRANSPARENCY_PROJECTION_MATCH",
    }
    return {**facts, "snapshot_digest_sha256": canonical_digest(facts)}


def evaluate_policy(
    *,
    rules: dict,
    baseline_action: PolicyAction,
    baseline_reason_codes: list[str],
    match_status: MatchStatus | str,
    coverage_status: CoverageStatus | str,
    rights_path: RightsPath | str,
    rights_facts: dict,
    ai_origin_classification: str | None = None,
    creator_profile_tier: str | None = None,
    origin_policy_mode: str | None = None,
    style_review_recommended: bool = False,
) -> dict:
    """Apply one immutable stored policy to evidence and persisted rights facts.

    A match may become a pass only through a currently effective persisted
    License row. If configured, that licence must be linked to a currently
    corroborated persisted Claim. No denormalized Work field participates.
    """
    merged = {**DEFAULT_POLICY_RULES, **(rules or {})}
    matched_rules: list[str] = []
    reason_codes = list(baseline_reason_codes)
    action = PolicyAction(str(baseline_action))
    missing_facts = list(rights_facts.get("missing_facts") or [])
    match_status = MatchStatus(str(match_status))
    coverage_status = CoverageStatus(str(coverage_status))
    derived_rights_path = RightsPath(
        str(rights_facts.get("derived_rights_path") or RightsPath.NO_LICENSE_INFO)
    )

    if match_status == MatchStatus.MATCH_FOUND:
        matched_rules.append("persisted_rights_facts_are_authoritative")
        scope_authorizing = list(rights_facts.get("scope_authorizing_license_ids") or [])
        strongly_authorizing = list(rights_facts.get("strongly_authorizing_license_ids") or [])
        eligible = (
            strongly_authorizing
            if merged.get("require_corroborated_claim_for_pass", True)
            else scope_authorizing
        )
        if coverage_status == CoverageStatus.COMPLETE and eligible:
            action = PolicyAction.PASS_BY_POLICY
            reason_codes.append("PERSISTED_LICENSE_PERMITS_INTENDED_USE")
        else:
            action = PolicyAction.REVIEW
            reason_codes.append("MATCH_WITHOUT_AUTHORIZING_PERSISTED_LICENSE")
            reason_codes.extend(rights_facts.get("claim_reason_codes") or [])
            reason_codes.extend(rights_facts.get("license_reason_codes") or [])

    blocking = list(rights_facts.get("blocking_reason_codes") or [])
    if blocking:
        matched_rules.append("terminal_rights_state_cannot_authorize")
        reason_codes.extend(blocking)
        action = PolicyAction.REVIEW if action == PolicyAction.PASS_BY_POLICY else action

    if (
        merged.get("require_complete_coverage_for_pass", True)
        and coverage_status != CoverageStatus.COMPLETE
    ):
        matched_rules.append("require_complete_coverage_for_pass")
        if (
            action == PolicyAction.PASS_BY_POLICY
            and match_status != MatchStatus.NO_MATCH_IN_CHECKED_SOURCES
        ):
            action = PolicyAction.REVIEW
            reason_codes.append("INCOMPLETE_COVERAGE_BLOCKS_PASS")

    if (
        merged.get("require_corroborated_claim_for_pass", True)
        and match_status == MatchStatus.MATCH_FOUND
        and action == PolicyAction.PASS_BY_POLICY
        and "NO_CORROBORATED_CLAIM" in missing_facts
    ):
        matched_rules.append("require_corroborated_claim_for_pass")
        action = PolicyAction.REVIEW
        reason_codes.append("MATCH_WITHOUT_CORROBORATED_CLAIM")

    escalate = merged.get("escalate_on") or {}
    if ai_origin_classification and ai_origin_classification in (
        escalate.get("ai_origin_classification") or []
    ):
        matched_rules.append("escalate_on.ai_origin_classification")
        if action == PolicyAction.PASS_BY_POLICY:
            action = PolicyAction.REVIEW
            reason_codes.append("AI_ORIGIN_CLASSIFICATION_ESCALATED_BY_POLICY")
    if creator_profile_tier and creator_profile_tier in (
        escalate.get("creator_profile_tier") or []
    ):
        # Resemblance is advisory: it may add review, never a block or a pass.
        matched_rules.append("escalate_on.creator_profile_tier")
        if action == PolicyAction.PASS_BY_POLICY:
            action = PolicyAction.REVIEW
            reason_codes.append("CREATOR_PROFILE_RESEMBLANCE_ESCALATED_BY_POLICY")

    required_origin_mode = bool(
        merged.get("honor_required_origin_policy_mode", True)
        and str(origin_policy_mode or "") == "REQUIRED"
    )
    if required_origin_mode and ai_origin_classification:
        matched_rules.append("honor_required_origin_policy_mode")
        if (
            ai_origin_classification != "NO_AI_ORIGIN_EVIDENCE_DETECTED"
            and action == PolicyAction.PASS_BY_POLICY
        ):
            action = PolicyAction.REVIEW
            reason_codes.extend(
                [
                    "AI_ORIGIN_RESULT_REQUIRES_PRODUCT_REVIEW",
                    "AI_ORIGIN_REVIEW_IS_NOT_INFRINGEMENT_FINDING",
                ]
            )
    elif ai_origin_classification:
        reason_codes.append(
            "AI_ORIGIN_CHECK_DISABLED_BY_POLICY"
            if str(origin_policy_mode or "") == "DISABLED"
            else "AI_ORIGIN_INFORMATIONAL_ONLY"
        )
    if style_review_recommended and match_status != MatchStatus.MATCH_FOUND:
        reason_codes.append("STYLE_SIGNAL_NOT_AUTO_ESCALATED_WITHOUT_AI_ORIGIN_SUPPORT")

    if (
        merged.get("block_enabled", False)
        and match_status == MatchStatus.MATCH_FOUND
        and coverage_status == CoverageStatus.COMPLETE
        and blocking
    ):
        matched_rules.append("block_enabled")
        action = PolicyAction.BLOCK
        reason_codes.append("BLOCKED_BY_TENANT_POLICY_ON_TERMINAL_RIGHTS_STATE")

    if merged.get("review_on_missing_facts", True) and missing_facts:
        matched_rules.append("review_on_missing_facts")
        if action == PolicyAction.PASS_BY_POLICY and match_status == MatchStatus.MATCH_FOUND:
            action = PolicyAction.REVIEW

    return {
        "policy_action": str(action),
        "baseline_policy_action": str(baseline_action),
        "rights_path": str(
            derived_rights_path if match_status == MatchStatus.MATCH_FOUND else rights_path
        ),
        "matched_rules": matched_rules,
        "missing_facts": missing_facts,
        "reason_codes": sorted(set(reason_codes)),
        "authorizing_license_id": rights_facts.get("authorizing_license_id"),
        "license_reason_codes": rights_facts.get("license_reason_codes") or [],
        "inputs": {
            "match_status": str(match_status),
            "coverage_status": str(coverage_status),
            "rights_path": str(rights_path),
            "intended_use_authorized": bool(rights_facts.get("authorizing_license_id")),
            "ai_origin_classification": ai_origin_classification,
            "creator_profile_tier": creator_profile_tier,
            "origin_policy_mode": origin_policy_mode,
            "rights_facts_snapshot_digest_sha256": rights_facts.get("snapshot_digest_sha256"),
        },
        "notes": [
            "A pass is a policy outcome for the declared scope, not a legal clearance finding.",
            "Creator-profile resemblance is advisory and cannot authorize or block on its own.",
        ],
    }


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
