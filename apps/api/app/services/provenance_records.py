"""Safe, immutable provenance projections and bounded image metadata inspection."""

from __future__ import annotations

import hashlib
from io import BytesIO
from typing import Any
from xml.etree import ElementTree

from PIL import Image, IptcImagePlugin
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ProvenanceIngredient, ProvenanceRecord


def normalized_status(value: Any, reasons: list[str], *, available: bool = True) -> str:
    if not available or any(
        "UNAVAILABLE" in code or "NOT_CONFIGURED" in code or "BINARY_NOT_FOUND" in code
        for code in reasons
    ):
        return "PROVIDER_UNAVAILABLE"
    if any("UNSUPPORTED" in code for code in reasons):
        return "UNSUPPORTED"
    if any("TIMEOUT" in code or "EXECUTION_FAILED" in code for code in reasons):
        return "PROVIDER_UNAVAILABLE"
    return {
        "VALID_TRUSTED": "VALID",
        "VALID_UNTRUSTED": "VALID_BUT_UNTRUSTED",
        "NOT_PRESENT": "ABSENT",
        "NOT_CHECKED": "UNSUPPORTED",
        "INVALID": "INVALID",
        "ERROR": "PARSE_ERROR",
    }.get(
        str(value),
        str(value)
        if str(value)
        in {
            "VALID",
            "VALID_BUT_UNTRUSTED",
            "ABSENT",
            "UNSUPPORTED",
            "PROVIDER_UNAVAILABLE",
            "PARSE_ERROR",
        }
        else "UNSUPPORTED",
    )


def _text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    # All text is untrusted metadata. Remove controls; only short allowlisted
    # software/device/model/action fields are retained, never comments or GPS.
    return "".join(char for char in str(value) if char.isprintable())[:240]


def inspect_metadata(raw: bytes) -> dict:
    result: dict[str, Any] = {
        "schema": "creatorproof.metadata-summary.v1",
        "raw_metadata_included": False,
        "removal_status": "UNKNOWN",
        "reason_codes": [],
    }
    try:
        with Image.open(BytesIO(raw)) as image:
            exif = image.getexif()
            result["exif"] = {
                "present": bool(exif),
                "tag_count": len(exif),
                "software": _text(exif.get(305)),
                "device_make": _text(exif.get(271)),
                "device_model": _text(exif.get(272)),
                "personal_fields_omitted": True,
            }
            iptc = IptcImagePlugin.getiptcinfo(image) or {}
            result["iptc"] = {
                "present": bool(iptc),
                "dataset_count": len(iptc),
                "personal_fields_omitted": True,
            }
            xmp = image.info.get("xmp") or image.info.get("XML:com.adobe.xmp")
            result["xmp"] = {"present": bool(xmp), "fields": {}}
            if xmp:
                encoded = xmp.encode() if isinstance(xmp, str) else bytes(xmp)
                if (
                    len(encoded) > 262_144
                    or b"<!DOCTYPE" in encoded.upper()
                    or b"<!ENTITY" in encoded.upper()
                ):
                    result["reason_codes"].append("XMP_UNSAFE_OR_OVERSIZED")
                else:
                    root = ElementTree.fromstring(encoded)
                    fields = {}
                    allowed = {"CreatorTool", "Software", "Make", "Model"}
                    for node in root.iter():
                        name = node.tag.rsplit("}", 1)[-1]
                        if name in allowed and node.text:
                            fields[name] = _text(node.text)
                        for key, value in node.attrib.items():
                            name = key.rsplit("}", 1)[-1]
                            if name in allowed:
                                fields[name] = _text(value)
                    result["xmp"]["fields"] = fields
            if not exif and not iptc and not xmp:
                result["reason_codes"].append("METADATA_ABSENT_NOT_PROOF_OF_REMOVAL")
    except (OSError, ValueError, TypeError, ElementTree.ParseError):
        result["reason_codes"].append("METADATA_PARSE_ERROR")
    return result


def persist_provenance(
    db: Session,
    *,
    tenant_id: str,
    subject_type: str,
    subject_id: str,
    input_sha256: str,
    evidence: dict,
    provider_status: dict | None = None,
    raw: bytes | None = None,
) -> ProvenanceRecord:
    provider_status = provider_status or {}
    previous = db.scalar(
        select(ProvenanceRecord)
        .where(
            ProvenanceRecord.tenant_id == tenant_id,
            ProvenanceRecord.subject_type == subject_type,
            ProvenanceRecord.subject_id == subject_id,
            ProvenanceRecord.input_sha256 == input_sha256,
            ProvenanceRecord.provider == str(evidence.get("provider") or "unknown"),
            ProvenanceRecord.provider_version == provider_status.get("binary_version"),
        )
        .order_by(ProvenanceRecord.created_at.desc())
        .limit(1)
    )
    reasons = list(evidence.get("reason_codes") or [])
    status = normalized_status(
        evidence.get("status"), reasons, available=provider_status.get("available", True)
    )
    summary = dict(evidence.get("manifest_summary") or {})
    if (
        previous is not None
        and previous.status == status
        and status not in {"PROVIDER_UNAVAILABLE", "PARSE_ERROR"}
        and previous.manifest_summary == summary
        and previous.trust_details == dict(evidence.get("trust_details") or {})
        and previous.reason_codes == reasons
    ):
        return previous
    row = ProvenanceRecord(
        tenant_id=tenant_id,
        subject_type=subject_type,
        subject_id=subject_id,
        scan_id=subject_id if subject_type == "scan" else None,
        work_id=subject_id if subject_type == "work" else None,
        input_sha256=input_sha256,
        provider=str(evidence.get("provider") or "unknown"),
        provider_version=provider_status.get("binary_version"),
        status=status,
        legacy_status=str(evidence.get("status")),
        reason_codes=reasons,
        manifest_summary=summary,
        trust_details=dict(evidence.get("trust_details") or {}),
        metadata_summary=inspect_metadata(raw) if raw else {"status": "NOT_RETAINED"},
        artifact_refs=[],
        fallback_used=status == "PROVIDER_UNAVAILABLE",
        error_code=reasons[0]
        if status in {"PROVIDER_UNAVAILABLE", "PARSE_ERROR"} and reasons
        else None,
    )
    db.add(row)
    db.flush()
    for index, item in enumerate(summary.get("ingredients") or []):
        if not isinstance(item, dict):
            continue
        identity = str(item.get("identifier_sha256") or item.get("hash") or index)
        if len(identity) > 64:
            identity = hashlib.sha256(identity.encode()).hexdigest()
        db.add(
            ProvenanceIngredient(
                tenant_id=tenant_id,
                record_id=row.id,
                ingredient_id=identity,
                relationship=_text(item.get("relationship")) or "INGREDIENT",
                input_sha256=item.get("sha256"),
                trust_status=item.get("validation_status"),
                metadata_summary={
                    "manifest_reference_sha256": item.get("manifest_reference_sha256")
                },
            )
        )
    return row
