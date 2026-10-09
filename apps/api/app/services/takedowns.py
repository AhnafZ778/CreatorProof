"""Jurisdiction-aware, reviewable notice drafting.

The templates are operator aids. They never turn a model score into a legal
finding and they never send a notice without an explicit human action.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.services.admin_review import positive_origin


@dataclass(frozen=True, slots=True)
class JurisdictionTemplate:
    code: str
    label: str
    basis: str
    checklist: tuple[str, ...]


TEMPLATES: dict[str, JurisdictionTemplate] = {
    "US": JurisdictionTemplate(
        "US",
        "United States — DMCA §512(c)(3)",
        "17 U.S.C. §512(c)(3) notice of claimed infringement",
        (
            "Identify the copyrighted work and attach or link the protected registration.",
            "Identify each allegedly infringing URL and the material to be removed.",
            "Include claimant contact details and a good-faith statement.",
            "Include the accuracy/authority declaration under penalty of perjury and a signature.",
        ),
    ),
    "EU": JurisdictionTemplate(
        "EU",
        "European Union — DSA notice-and-action",
        "Regulation (EU) 2022/2065 Digital Services Act notice-and-action mechanism",
        (
            (
                "Give the exact electronic location of the content and explain why it is "
                "illegal under the applicable national law."
            ),
            "Use the platform's DSA notice channel and include contact details for follow-up.",
            (
                "State that the notice is submitted in good faith and is accurate to the "
                "best of the notifier's knowledge."
            ),
            "Retain the platform acknowledgement and appeal/complaint response.",
        ),
    ),
    "UK": JurisdictionTemplate(
        "UK",
        "United Kingdom — copyright infringement notice",
        "Copyright, Designs and Patents Act 1988 and platform notice procedure",
        (
            "Identify the protected work, ownership basis, and the exact infringing location.",
            "Request removal or disabling of access and include contact details and signature.",
            "Use the host's designated copyright reporting channel and retain its response.",
        ),
    ),
    "CA": JurisdictionTemplate(
        "CA",
        "Canada — copyright notice",
        "Copyright Act notice-and-notice process and the host's reporting procedure",
        (
            (
                "Identify the work and the allegedly infringing location with enough detail "
                "to find it."
            ),
            "State the claimant's ownership or authority and requested remedy.",
            (
                "Use the host's designated reporting channel; do not request personal "
                "information outside the process."
            ),
        ),
    ),
    "AU": JurisdictionTemplate(
        "AU",
        "Australia — copyright removal request",
        "Copyright Act 1968 and the host's copyright reporting procedure",
        (
            "Identify the original work, the claimant, and the exact copied location.",
            "Explain the rights basis and request removal or disabling of access.",
            "Include contact details, good-faith confirmation, and a signature.",
        ),
    ),
    "GENERIC": JurisdictionTemplate(
        "GENERIC",
        "International — platform copyright notice",
        "The platform's copyright or illegal-content reporting procedure",
        (
            "Identify the protected work and the exact location of the disputed copy.",
            (
                "Explain the rights basis, requested remedy, and how the platform can "
                "contact the claimant."
            ),
            "Attach evidence and submit through the host's official reporting channel.",
        ),
    ),
}


def normalize_jurisdiction(country_code: str | None) -> str:
    code = str(country_code or "").strip().upper()
    if code == "GB":
        return "UK"
    if code in {"US", "CA", "AU", "UK", "EU"}:
        return code
    if code in {
        "AT",
        "BE",
        "BG",
        "HR",
        "CY",
        "CZ",
        "DK",
        "EE",
        "FI",
        "FR",
        "DE",
        "GR",
        "HU",
        "IE",
        "IT",
        "LV",
        "LT",
        "LU",
        "MT",
        "NL",
        "PL",
        "PT",
        "RO",
        "SK",
        "SI",
        "ES",
        "SE",
    }:
        return "EU"
    return "GENERIC"


def infer_country(metadata: dict | None, source_url: str) -> tuple[str | None, str]:
    """Use only explicit provider metadata; never deanonymize a creator."""
    data = metadata if isinstance(metadata, dict) else {}
    for key in ("country_code", "creator_country", "country"):
        value = str(data.get(key) or "").strip().upper()
        if re.fullmatch(r"[A-Z]{2}", value):
            return value, f"explicit_provider_metadata:{key}"
    host = source_url.split("/", 3)[2].lower() if source_url.startswith("https://") else ""
    suffixes = {"co.uk": "UK", "ca": "CA", "au": "AU"}
    for suffix, code in suffixes.items():
        if host.endswith(f".{suffix}") or host == suffix:
            return code, f"source_host_suffix:{suffix}"
    return None, "not_available_from_provider_metadata"


def classify_scan(scan) -> str:
    packet = scan.evidence_packet or {}
    ai_signal = positive_origin(packet)
    copied = str(scan.match_status or "").upper() == "MATCH_FOUND"
    if copied and ai_signal:
        return "AI_GENERATED_VERSION"
    if copied:
        return "COPIED"
    if ai_signal:
        return "AI_GENERATED"
    return "UNCLASSIFIED"


def build_notice(
    *,
    jurisdiction: str,
    claimant_name: str,
    claimant_email: str,
    protected_title: str,
    protected_url: str,
    infringing_url: str,
    evidence_summary: str,
    creator_name: str | None,
) -> tuple[str, str]:
    template = TEMPLATES.get(normalize_jurisdiction(jurisdiction), TEMPLATES["GENERIC"])
    subject = f"{template.label}: request to remove unauthorized artwork — {protected_title}"
    checklist = "\n".join(f"- {item}" for item in template.checklist)
    requested_action = (
        "Requested action: please review this notice and remove or disable access to the "
        "identified material, or explain the platform's applicable dispute process."
    )
    declaration = (
        "I state that I have a good-faith belief that the use described above is not "
        "authorized by the copyright owner, its agent, or the law. I state that the "
        "information in this notice is accurate and, where required, that I am authorized "
        "to act for the owner. I understand that this notice is a request for platform "
        "action and not a court judgment."
    )
    body = f"""To the designated copyright or legal contact,

I am {claimant_name}, the copyright owner or authorized agent for the work “{protected_title}”.

Protected work: {protected_url}
Allegedly infringing location: {infringing_url}
Observed creator/profile: {creator_name or "Not available from the provider"}

Evidence summary:
{evidence_summary}

{requested_action}

{template.basis}

{declaration}

Claimant: {claimant_name}
Contact: {claimant_email}
Signature: {claimant_name}
Date: ____________________

Operator checklist before sending:
{checklist}
"""
    return subject, body
