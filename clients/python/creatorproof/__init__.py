"""Typed Python client for the CreatorProof API.

Depends only on the standard library so a customer can integrate without
adopting this project's dependency set. Every method maps to one documented
endpoint and returns typed dataclasses rather than loose dictionaries, and the
raw response body is always retained so nothing the API said is lost.
"""

from .client import (
    CreatorProofClient,
    CreatorProofError,
    ProofReceipt,
    ReviewCase,
    ScanResult,
    StageTimeline,
    VerificationPackage,
    Work,
    verify_webhook_signature,
)

__all__ = [
    "CreatorProofClient",
    "CreatorProofError",
    "ProofReceipt",
    "ReviewCase",
    "ScanResult",
    "StageTimeline",
    "VerificationPackage",
    "Work",
    "verify_webhook_signature",
]
__version__ = "0.9.2"
