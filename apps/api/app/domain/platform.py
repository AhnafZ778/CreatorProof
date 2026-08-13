"""Part 2 platform vocabulary.

These enums are owned by the platform/orchestration layer. They are deliberately
kept out of ``app.domain.enums`` so the Part 1 evidence contract (match status,
coverage status, capability execution state, policy action, anchor status) stays
byte-stable for Agent A, the Evidence Packet v1 readers, and the frontend.
"""

from enum import StrEnum


class ScanLifecycleState(StrEnum):
    """Durable orchestration state.

    ``Scan.state`` keeps the coarse v1 vocabulary for API compatibility. This
    richer lifecycle is recorded alongside it and drives recovery decisions.
    """

    ACCEPTED = "ACCEPTED"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    RESULT_READY = "RESULT_READY"
    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class StageName(StrEnum):
    """Durable stages of the scan pipeline.

    ``PROOF`` is intentionally last and separate: a proof failure must never
    rewrite a committed evidence finding.
    """

    INTAKE = "INTAKE"
    EVIDENCE = "EVIDENCE"
    STATEMENT = "STATEMENT"
    PROOF = "PROOF"
    NOTIFY = "NOTIFY"


class StageState(StrEnum):
    PENDING = "PENDING"
    READY = "READY"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED_RETRYABLE = "FAILED_RETRYABLE"
    FAILED_TERMINAL = "FAILED_TERMINAL"
    SKIPPED_BY_POLICY = "SKIPPED_BY_POLICY"
    CANCELLED = "CANCELLED"


class WorkerClass(StrEnum):
    """Explicit routing so unavailable capacity is observable per worker role."""

    CPU = "CPU"
    GPU = "GPU"
    PROOF = "PROOF"
    NOTIFY = "NOTIFY"


class RetryClass(StrEnum):
    """Typed failure classification. Only TRANSIENT is retried."""

    TRANSIENT = "TRANSIENT"
    TERMINAL = "TERMINAL"
    INVARIANT_VIOLATION = "INVARIANT_VIOLATION"
    CANCELLED = "CANCELLED"


class OutboxState(StrEnum):
    PENDING = "PENDING"
    PUBLISHED = "PUBLISHED"
    FAILED = "FAILED"


class BlockchainCommitmentType(StrEnum):
    """Purpose-specific public commitments; never store private evidence on-chain."""

    EVIDENCE_PACKET = "EVIDENCE_PACKET"
    TRANSPARENCY_CHECKPOINT = "TRANSPARENCY_CHECKPOINT"
    COUNTERPARTY_ATTESTATION = "COUNTERPARTY_ATTESTATION"


class NetworkMemberRole(StrEnum):
    """Why an organization is in the attestation network, not what it owns."""

    PLATFORM = "PLATFORM"
    CREATOR = "CREATOR"
    AGENCY = "AGENCY"
    BRAND = "BRAND"
    MARKETPLACE = "MARKETPLACE"
    REVIEWER = "REVIEWER"
    REGULATOR_OBSERVER = "REGULATOR_OBSERVER"


class NetworkMemberStatus(StrEnum):
    """Membership lifecycle mirrored from the on-chain registry."""

    UNKNOWN = "UNKNOWN"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    OFFBOARDED = "OFFBOARDED"


# The registry contract stores roles and statuses as uint8. These maps are the
# single translation point between Solidity and Python; changing either side
# without the other is a schema break.
NETWORK_MEMBER_ROLE_CODES: dict[int, NetworkMemberRole] = {
    1: NetworkMemberRole.PLATFORM,
    2: NetworkMemberRole.CREATOR,
    3: NetworkMemberRole.AGENCY,
    4: NetworkMemberRole.BRAND,
    5: NetworkMemberRole.MARKETPLACE,
    6: NetworkMemberRole.REVIEWER,
    7: NetworkMemberRole.REGULATOR_OBSERVER,
}
NETWORK_MEMBER_ROLE_VALUES: dict[NetworkMemberRole, int] = {
    role: code for code, role in NETWORK_MEMBER_ROLE_CODES.items()
}
NETWORK_MEMBER_STATUS_CODES: dict[int, NetworkMemberStatus] = {
    0: NetworkMemberStatus.UNKNOWN,
    1: NetworkMemberStatus.ACTIVE,
    2: NetworkMemberStatus.SUSPENDED,
    3: NetworkMemberStatus.OFFBOARDED,
}


class CounterpartyDecision(StrEnum):
    """A counterparty's own position on a clearance result.

    This is the party's commitment, deliberately distinct from CreatorProof's
    machine policy action and from a human reviewer's disposition.
    """

    ACKNOWLEDGED = "ACKNOWLEDGED"
    ACCEPTED_FOR_PUBLICATION = "ACCEPTED_FOR_PUBLICATION"
    REJECTED_FOR_PUBLICATION = "REJECTED_FOR_PUBLICATION"
    LICENSE_REQUIRED = "LICENSE_REQUIRED"
    DISPUTED = "DISPUTED"


class CounterpartyAttestationState(StrEnum):
    """Lifecycle of one counterparty commitment and its public anchor."""

    SIGNED = "SIGNED"
    ANCHOR_PENDING = "ANCHOR_PENDING"
    ANCHORED = "ANCHORED"
    ANCHOR_FAILED = "ANCHOR_FAILED"
    WITHDRAWN = "WITHDRAWN"


class BlockchainAnchorJobState(StrEnum):
    """Durable transaction lifecycle used by the EVM reconciliation worker."""

    PENDING = "PENDING"
    PREPARED = "PREPARED"
    SUBMITTED = "SUBMITTED"
    CONFIRMED = "CONFIRMED"
    RETRYABLE = "RETRYABLE"
    FAILED = "FAILED"


class PrincipalRole(StrEnum):
    ORG_ADMIN = "ORG_ADMIN"
    CATALOG_MANAGER = "CATALOG_MANAGER"
    REVIEWER = "REVIEWER"
    AUDITOR = "AUDITOR"
    SERVICE_ACCOUNT = "SERVICE_ACCOUNT"


class CredentialScope(StrEnum):
    WORKS_READ = "works:read"
    WORKS_WRITE = "works:write"
    SCANS_READ = "scans:read"
    SCANS_WRITE = "scans:write"
    RIGHTS_READ = "rights:read"
    RIGHTS_WRITE = "rights:write"
    REVIEW_READ = "review:read"
    REVIEW_WRITE = "review:write"
    ADMIN = "admin"


ROLE_SCOPES: dict[PrincipalRole, frozenset[CredentialScope]] = {
    PrincipalRole.ORG_ADMIN: frozenset(CredentialScope),
    PrincipalRole.CATALOG_MANAGER: frozenset(
        {
            CredentialScope.WORKS_READ,
            CredentialScope.WORKS_WRITE,
            CredentialScope.SCANS_READ,
            CredentialScope.SCANS_WRITE,
            CredentialScope.RIGHTS_READ,
            CredentialScope.RIGHTS_WRITE,
        }
    ),
    PrincipalRole.REVIEWER: frozenset(
        {
            CredentialScope.WORKS_READ,
            CredentialScope.SCANS_READ,
            CredentialScope.RIGHTS_READ,
            CredentialScope.REVIEW_READ,
            CredentialScope.REVIEW_WRITE,
        }
    ),
    PrincipalRole.AUDITOR: frozenset(
        {
            CredentialScope.WORKS_READ,
            CredentialScope.SCANS_READ,
            CredentialScope.RIGHTS_READ,
            CredentialScope.REVIEW_READ,
        }
    ),
    PrincipalRole.SERVICE_ACCOUNT: frozenset(
        {
            CredentialScope.WORKS_READ,
            CredentialScope.WORKS_WRITE,
            CredentialScope.SCANS_READ,
            CredentialScope.SCANS_WRITE,
        }
    ),
}


class StatementType(StrEnum):
    """Append-only evidence lineage. Corrections never mutate a prior statement."""

    RESULT = "RESULT"
    CORRECTION = "CORRECTION"
    DISPUTE = "DISPUTE"
    SUPERSESSION = "SUPERSESSION"
    REVOCATION = "REVOCATION"


class StatementStatus(StrEnum):
    ACTIVE = "ACTIVE"
    DISPUTED = "DISPUTED"
    SUPERSEDED = "SUPERSEDED"
    REVOKED = "REVOKED"


class ReviewCaseState(StrEnum):
    OPEN = "OPEN"
    IN_REVIEW = "IN_REVIEW"
    AWAITING_INFORMATION = "AWAITING_INFORMATION"
    DISPUTED = "DISPUTED"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


class ReviewEventType(StrEnum):
    CREATED = "CREATED"
    ASSIGNED = "ASSIGNED"
    COMMENTED = "COMMENTED"
    EVIDENCE_REQUESTED = "EVIDENCE_REQUESTED"
    DISPUTE_RAISED = "DISPUTE_RAISED"
    DISPUTE_RESPONSE = "DISPUTE_RESPONSE"
    APPEALED = "APPEALED"
    DECIDED = "DECIDED"
    REOPENED = "REOPENED"
    CLOSED = "CLOSED"


class ReviewDisposition(StrEnum):
    """Human disposition, deliberately distinct from machine policy action."""

    NOT_DECIDED = "NOT_DECIDED"
    APPROVED_FOR_PUBLICATION = "APPROVED_FOR_PUBLICATION"
    REJECTED_FOR_PUBLICATION = "REJECTED_FOR_PUBLICATION"
    ESCALATED = "ESCALATED"
    NEEDS_LICENSE = "NEEDS_LICENSE"


class WebhookDeliveryState(StrEnum):
    PENDING = "PENDING"
    DELIVERED = "DELIVERED"
    RETRYING = "RETRYING"
    DEAD_LETTERED = "DEAD_LETTERED"


class DeletionReceiptState(StrEnum):
    REQUESTED = "REQUESTED"
    COMPLETED = "COMPLETED"
    COMPLETED_WITH_EXCEPTIONS = "COMPLETED_WITH_EXCEPTIONS"
    FAILED = "FAILED"


class LicenseState(StrEnum):
    """Only ACTIVE licenses can contribute to an authorized use."""

    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"
    SUPERSEDED = "SUPERSEDED"


class PartyVerificationState(StrEnum):
    """Identity verification is a separate fact from authorship or ownership."""

    UNVERIFIED = "UNVERIFIED"
    EMAIL_VERIFIED = "EMAIL_VERIFIED"
    DOCUMENT_VERIFIED = "DOCUMENT_VERIFIED"
    CREDENTIAL_VERIFIED = "CREDENTIAL_VERIFIED"


class RightsEventType(StrEnum):
    CORROBORATED = "CORROBORATED"
    DISPUTED = "DISPUTED"
    SUPERSEDED = "SUPERSEDED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class AuditEventType(StrEnum):
    CREDENTIAL_CREATED = "CREDENTIAL_CREATED"
    CREDENTIAL_REVOKED = "CREDENTIAL_REVOKED"
    AUTH_FAILED = "AUTH_FAILED"
    RATE_LIMITED = "RATE_LIMITED"
    WORK_REGISTERED = "WORK_REGISTERED"
    SCAN_ACCEPTED = "SCAN_ACCEPTED"
    SCAN_CANCELLED = "SCAN_CANCELLED"
    STATEMENT_ISSUED = "STATEMENT_ISSUED"
    PROOF_ANCHORED = "PROOF_ANCHORED"
    RIGHTS_CHANGED = "RIGHTS_CHANGED"
    POLICY_CREATED = "POLICY_CREATED"
    REVIEW_ACTION = "REVIEW_ACTION"
    DELETION_REQUESTED = "DELETION_REQUESTED"
    BREAK_GLASS_ACCESS = "BREAK_GLASS_ACCESS"
