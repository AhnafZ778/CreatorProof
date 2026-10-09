"""Register project-owned art, run real offline comparisons, and save their review files.

Idempotent by image hash and scan request key. No provider calls or outgoing notices.
Published images belong to the first-party CreatorProof collection; these records do
not establish unauthorized third-party use. Scans keep their actual provider coverage.
"""

from __future__ import annotations

import argparse
import hashlib
import time
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import Settings
from app.main import create_app
from app.models import Scan, TakedownDraft, Work
from app.services.case_archive import save_comparison
from app.services.takedowns import build_notice
from app.services.tenancy import bind_tenant_context

ROOT = Path(__file__).resolve().parents[3]
ASSETS = ROOT / "apps/web/public/case-library"
CATALOG = "creatorproof-collection"
CASES = [
    {
        "slug": "nocturne-republication",
        "original": "nocturne-original.png",
        "candidate": "nocturne-republished.png",
        "title": "Nocturne",
        "case_title": "Nocturne · full-image republication",
        "country": "US",
        "kind": "COPY",
        "caption": "The complete composition appears again, "
        "with a byte-identical registered reference.",
    },
    {
        "slug": "garden-publication",
        "original": "garden-original.png",
        "candidate": "garden-cropped.png",
        "title": "Tidal Garden",
        "case_title": "Tidal Garden · cropped publication",
        "country": "FR",
        "kind": "CROP",
        "caption": "A tighter frame preserves the original illustration. "
        "Inspect the recorded geometric match.",
    },
    {
        "slug": "nocturne-sky-edit",
        "original": "nocturne-original.png",
        "candidate": "nocturne-ai-edit.png",
        "title": "Nocturne",
        "case_title": "Nocturne · AI sky edit",
        "country": "GB",
        "kind": "AI_EDIT",
        "caption": "An AI-edited sky surrounds the retained arch and city. "
        "Editing history accompanies the comparison.",
    },
]


def preload(settings: Settings, *, base_url: str):
    if settings.environment == "production":
        raise ValueError("Preloading requires a local development installation.")
    settings = settings.model_copy(
        update={
            # Honor the inline queue and suppress background webhook dispatch.
            "environment": "test",
            "job_backend": "inline",
            "candidate_retention_seconds": 604800,
            "admin_archive_matches": False,
            "synthetic_detector": "off",
            "c2pa_mode": "off",
            "style_provider": "diagnostic",
            "registration_origin_gate": "OFF",
            "copy_retrieval_requirement": "BASELINE_ALLOWED",
            "proof_anchor_mode": "none",
            "proof_require_chain": False,
            "sightengine_api_user": "",
            "sightengine_api_secret": "",
            "aiand_api_key": "",
            "visible_ai_marker_mode": "off",
            "sscd_model_path": ASSETS / "unconfigured-sscd.pt",
            "synthetic_policy_mode": "INFORMATIONAL",
        }
    )
    app = create_app(settings)
    headers = {"X-API-Key": settings.dev_api_key}
    results = []
    with TestClient(app) as client:
        container = app.state.container
        for item in CASES:
            reference = (ASSETS / item["original"]).read_bytes()
            candidate = (ASSETS / item["candidate"]).read_bytes()
            with container.database.session_factory() as db:
                bind_tenant_context(db, settings.dev_tenant_id)
                work = db.scalar(
                    select(Work).where(
                        Work.tenant_id == settings.dev_tenant_id,
                        Work.catalog_id == CATALOG,
                        Work.sha256 == hashlib.sha256(reference).hexdigest(),
                        Work.deleted_at.is_(None),
                    )
                )
                work_id = work.id if work else None
            if work_id is None:
                response = client.post(
                    "/v1/works",
                    headers=headers,
                    data={
                        "title": item["title"],
                        "catalog_id": CATALOG,
                        "claimant": "CreatorProof collection",
                        "rights_path": "NO_LICENSE_INFO",
                    },
                    files={"file": (item["original"], reference, "image/png")},
                )
                response.raise_for_status()
                work_id = response.json()["id"]
            key = (
                "stored-collection-v1-"
                + item["slug"]
                + "-"
                + hashlib.sha256(candidate).hexdigest()[:16]
            )
            with container.database.session_factory() as db:
                bind_tenant_context(db, settings.dev_tenant_id)
                previous = db.scalar(
                    select(Scan).where(
                        Scan.tenant_id == settings.dev_tenant_id, Scan.idempotency_key == key
                    )
                )
                scan_id = previous.id if previous else None
            protected_url = (
                base_url
                + "/collection/"
                + ("garden" if item["title"] == "Tidal Garden" else "nocturne")
            )
            source_url = base_url + "/collection/" + item["slug"]
            if scan_id is None:
                response = client.post(
                    "/v1/scans",
                    headers={**headers, "Idempotency-Key": key},
                    data={
                        "catalog_id": CATALOG,
                        "intended_use": "commercial publication",
                        "country_code": item["country"],
                        "source_url": source_url,
                        "use_context": '{"channel":"website","audience":"public",'
                        '"platform":"CreatorProof collection"}',
                    },
                    files={"file": (item["candidate"], candidate, "image/png")},
                )
                response.raise_for_status()
                scan_id = response.json()["id"]
            deadline = time.monotonic() + 120
            while True:
                result = client.get(f"/v1/scans/{scan_id}", headers=headers)
                result.raise_for_status()
                if result.json()["state"] in {"COMPLETED", "FAILED"}:
                    break
                if time.monotonic() >= deadline:
                    raise RuntimeError(f"{item['slug']}: scan completion timed out")
                time.sleep(0.5)
            with container.database.session_factory() as db:
                bind_tenant_context(db, settings.dev_tenant_id)
                scan = db.get(Scan, scan_id)
                if scan.state != "COMPLETED" or scan.match_status != "MATCH_FOUND":
                    raise RuntimeError(
                        f"{item['slug']}: scan did not establish a match ({scan.match_status})"
                    )
                jurisdiction = {"US": "US", "FR": "EU", "GB": "UK"}[item["country"]]
                summary = (
                    f"CreatorProof scan {scan_id} recorded MATCH_FOUND against registered artwork "
                    f"{work_id}. Candidate SHA-256: {scan.candidate_sha256}. "
                    f"Reference SHA-256: {hashlib.sha256(reference).hexdigest()}. "
                    "The observed and original pages are first-party publications. "
                    "Permission, claimant authority and legal applicability "
                    "require human confirmation."
                )
                notice_context = {
                    "jurisdiction": jurisdiction,
                    "claimant_name": "CreatorProof collection",
                    "claimant_email": "rights@creatorproof.example",
                    "protected_url": protected_url,
                    "infringing_url": source_url,
                    "evidence_summary": summary,
                    "recipient_email": "",
                }
                context = {
                    "case_title": item["case_title"],
                    "caption": item["caption"],
                    "comparison_kind": item["kind"],
                    "notice_context": notice_context,
                    "source_note": "Source: CreatorProof collection · first-party publication. "
                    "Permission and claimant authority remain subject to review.",
                }
                if item["kind"] == "AI_EDIT":
                    context["generation_record"] = {
                        "provider": "OpenAI image generation",
                        "model": None,
                        "description": "The sky was edited with OpenAI image generation "
                        "from the registered original; architecture and composition "
                        "were requested to remain unchanged.",
                        "input_sha256": hashlib.sha256(reference).hexdigest(),
                        "output_sha256": hashlib.sha256(candidate).hexdigest(),
                        "artifact_id": "exec-3340f078-bb71-48a5-bdd7-05f83a096f9e",
                        "generated_at": datetime.fromtimestamp(
                            (ASSETS / item["candidate"]).stat().st_mtime, UTC
                        ).isoformat(),
                        "basis": "RECORDED_GENERATION_PROCESS",
                        "detector_conclusion": None,
                    }
                case = save_comparison(
                    container, db, scan, actor="collection-operator", context=context
                )
                saved = db.scalar(
                    select(TakedownDraft).where(
                        TakedownDraft.tenant_id == scan.tenant_id, TakedownDraft.scan_id == scan.id
                    )
                )
                if saved is None:
                    subject, body = build_notice(
                        jurisdiction=jurisdiction,
                        claimant_name=notice_context["claimant_name"],
                        claimant_email=notice_context["claimant_email"],
                        protected_title=item["title"],
                        protected_url=protected_url,
                        infringing_url=source_url,
                        evidence_summary=summary,
                        creator_name="CreatorProof collection",
                    )
                    body = (
                        "PREPARED FOR OPERATOR REVIEW\n\n"
                        "Claimant authority and unauthorized use have not been established. "
                        "Both publications are in the first-party CreatorProof collection. "
                        "The contact address is a reserved placeholder; replace it with "
                        "verified claimant contact. "
                        "The declarations below are proposed wording for claimant "
                        "confirmation and have not been attested. "
                        "Do not submit without establishing the required rights and facts.\n\n"
                        + body
                    )
                    db.add(
                        TakedownDraft(
                            tenant_id=scan.tenant_id,
                            scan_id=scan.id,
                            jurisdiction=jurisdiction,
                            recipient_country_code=item["country"],
                            subject=subject,
                            body=body,
                            generation_provider="template",
                            state="DRAFT",
                        )
                    )
                    db.commit()
                results.append(
                    {
                        "scan_id": scan.id,
                        "case_id": case.id,
                        "title": item["case_title"],
                        "match_status": scan.match_status,
                        "comparison_kind": item["kind"],
                    }
                )
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:3000")
    args = parser.parse_args()
    import json

    print(
        json.dumps(
            {"stored_cases": preload(Settings(), base_url=args.base_url.rstrip("/"))}, indent=2
        )
    )


if __name__ == "__main__":
    main()
