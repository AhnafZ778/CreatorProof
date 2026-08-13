from enum import StrEnum


class ScanState(StrEnum):
    QUEUED = "QUEUED"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class MatchStatus(StrEnum):
    MATCH_FOUND = "MATCH_FOUND"
    INCONCLUSIVE = "INCONCLUSIVE"
    NO_MATCH_IN_CHECKED_SOURCES = "NO_MATCH_IN_CHECKED_SOURCES"
    SCOPE_INCOMPLETE = "SCOPE_INCOMPLETE"
    ERROR = "ERROR"


class CoverageStatus(StrEnum):
    COMPLETE = "COMPLETE"
    EMPTY_SCOPE = "EMPTY_SCOPE"
    PARTIAL = "PARTIAL"
    DEGRADED = "DEGRADED"
    TRUNCATED = "TRUNCATED"
    FAILED = "FAILED"


class CoverageReasonCode(StrEnum):
    COVERAGE_MANIFEST_INCONSISTENT = "COVERAGE_MANIFEST_INCONSISTENT"
    DECLARED_CATALOG_EMPTY = "DECLARED_CATALOG_EMPTY"
    REQUIRED_LEARNED_RETRIEVAL_INCOMPLETE = "REQUIRED_LEARNED_RETRIEVAL_INCOMPLETE"
    CANDIDATE_VERIFICATION_TRUNCATED = "CANDIDATE_VERIFICATION_TRUNCATED"
    CANDIDATE_VERIFICATION_FAILURE = "CANDIDATE_VERIFICATION_FAILURE"
    CANDIDATE_VERIFICATION_PARTIAL = "CANDIDATE_VERIFICATION_PARTIAL"


class CapabilityExecutionState(StrEnum):
    NOT_CONFIGURED = "NOT_CONFIGURED"
    READY = "READY"
    EXECUTED = "EXECUTED"
    SKIPPED_BY_POLICY = "SKIPPED_BY_POLICY"
    UNAVAILABLE = "UNAVAILABLE"
    FAILED = "FAILED"


class OriginPolicyMode(StrEnum):
    DISABLED = "DISABLED"
    INFORMATIONAL = "INFORMATIONAL"
    REQUIRED = "REQUIRED"


class RegistrationOriginGate(StrEnum):
    """How work registration reacts to an AI-origin finding on the submitted file.

    A catalog of protected works is a record of human authorship, so an image the
    origin lane reports as AI-generated does not belong in it. Refusing is a
    decision about what this catalog will vouch for, not a finding about the
    person submitting it, and the three modes exist so an operator can choose
    where that line sits.
    """

    OFF = "OFF"
    """Do not run the check."""

    FLAG_ONLY = "FLAG_ONLY"
    """Run it and store the verdict on the work, but always accept the file."""

    BLOCK = "BLOCK"
    """Refuse the registration once the origin lane reports AI indicators."""


class CopyRetrievalRequirement(StrEnum):
    BASELINE_ALLOWED = "BASELINE_ALLOWED"
    LEARNED_REQUIRED = "LEARNED_REQUIRED"


class PolicyAction(StrEnum):
    PASS_BY_POLICY = "PASS_BY_POLICY"
    REVIEW = "REVIEW"
    BLOCK = "BLOCK"


class RightsPath(StrEnum):
    EXISTING_LICENSE = "EXISTING_LICENSE"
    LICENSE_AVAILABLE = "LICENSE_AVAILABLE"
    NO_LICENSE_INFO = "NO_LICENSE_INFO"
    DISPUTED = "DISPUTED"


class AnchorStatus(StrEnum):
    NOT_REQUESTED = "NOT_REQUESTED"
    PENDING = "PENDING"
    ANCHORED = "ANCHORED"
    FAILED = "FAILED"
    REVOKED = "REVOKED"


class ClaimState(StrEnum):
    ASSERTED = "ASSERTED"
    CORROBORATED = "CORROBORATED"
    DISPUTED = "DISPUTED"
    SUPERSEDED = "SUPERSEDED"
    REVOKED = "REVOKED"


class ProvenanceStatus(StrEnum):
    NOT_CHECKED = "NOT_CHECKED"
    NOT_PRESENT = "NOT_PRESENT"
    VALID_TRUSTED = "VALID_TRUSTED"
    VALID_UNTRUSTED = "VALID_UNTRUSTED"
    INVALID = "INVALID"
    ERROR = "ERROR"
