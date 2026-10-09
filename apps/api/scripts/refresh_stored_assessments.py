"""Run the configured detector pipeline once for locally stored comparisons.

The new scan is preserved independently. A hash-bound pointer links it to the
stored comparison without changing its original evidence or sending webhooks.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import Settings
from app.main import create_app
from app.models import ReviewCase, ReviewEvent, Scan, Work
from app.services.scan_runner import run_scan
from app.services.tenancy import bind_tenant_context


def refresh(settings: Settings, *, revision: str | None = None, comparison_kind: str | None = None):
    if settings.environment == "production":
        raise ValueError("Use this local preparation script outside production only.")
    isolated = settings.model_copy(
        update={
            "environment": "test",
            "job_backend": "inline",
            "admin_archive_matches": False,
            "proof_anchor_mode": "none",
            "proof_require_chain": False,
        }
    )
    app = create_app(isolated)
    headers = {"X-API-Key": isolated.dev_api_key}
    results = []
    with TestClient(app) as client:
        container = app.state.container
        with container.database.session_factory() as db:
            bind_tenant_context(db, isolated.dev_tenant_id)
            case_ids = db.scalars(
                select(ReviewCase.id).where(
                    ReviewCase.tenant_id == isolated.dev_tenant_id,
                    ReviewCase.archive_record["schema"].as_string()
                    == "creatorproof.stored-comparison.v1",
                )
            ).all()
        for case_id in case_ids:
            with container.database.session_factory() as db:
                bind_tenant_context(db, isolated.dev_tenant_id)
                case = db.get(ReviewCase, case_id)
                archive = case.archive_record
                kind = (archive.get("context") or {}).get("comparison_kind")
                if comparison_kind is not None and kind != comparison_kind:
                    continue
                old = db.get(Scan, case.scan_id)
                work = db.get(Work, archive["work_id"])
                if work is None or work.deleted_at is not None:
                    continue
                raw = container.storage.read(archive["candidate_key"])
                if hashlib.sha256(raw).hexdigest() != archive["candidate_sha256"]:
                    raise ValueError("Stored candidate hash mismatch")
                if work.sha256 != archive["reference_sha256"]:
                    raise ValueError("Stored reference hash mismatch")
                original_id = old.id
                submission = old.submission_context
                data = {
                    "catalog_id": old.catalog_id,
                    "intended_use": old.intended_use,
                    "use_context": json.dumps(submission.get("use_context") or {}),
                }
                if submission.get("country_code"):
                    data["country_code"] = submission["country_code"]
                if submission.get("source_url"):
                    data["source_url"] = submission["source_url"]
                run_revision = revision or ("v2" if kind == "AI_EDIT" else "v1")
                key = f"stored-full-assessment-{run_revision}-{case.id}"
                previous = db.scalar(
                    select(Scan).where(
                        Scan.tenant_id == old.tenant_id,
                        Scan.idempotency_key == key,
                    )
                )
                scan_id = previous.id if previous else None
                resume = previous is not None and previous.state not in {"COMPLETED", "FAILED"}
            if scan_id is None:
                response = client.post(
                    "/v1/scans",
                    headers={**headers, "Idempotency-Key": key},
                    data=data,
                    files={"file": ("comparison.png", raw, "image/png")},
                )
                response.raise_for_status()
                scan_id = response.json()["id"]
            elif resume:
                run_scan(container, scan_id)
            deadline = time.monotonic() + 1800
            while True:
                response = client.get(f"/v1/scans/{scan_id}", headers=headers)
                response.raise_for_status()
                result = response.json()
                if result["state"] in {"COMPLETED", "FAILED"}:
                    break
                if resume:
                    # A prior process can leave a stage leased until expiry.
                    # The ledger fences duplicate workers and reclaims expired leases.
                    run_scan(container, scan_id)
                if time.monotonic() > deadline:
                    raise RuntimeError("Assessment did not complete in time")
                time.sleep(1)
            if result["state"] != "COMPLETED":
                raise RuntimeError(f"Assessment failed: {scan_id}")
            with container.database.session_factory() as db:
                bind_tenant_context(db, isolated.dev_tenant_id)
                case = db.get(ReviewCase, case_id)
                if case.archive_record.get("assessment_scan_id") != scan_id:
                    case.archive_record = {**case.archive_record, "assessment_scan_id": scan_id}
                    db.add(
                        ReviewEvent(
                            tenant_id=case.tenant_id,
                            case_id=case.id,
                            event_type="ASSESSMENT_REFRESHED",
                            actor_label="collection-operator",
                            note="Configured models assessed the retained comparison; "
                            "original scan preserved.",
                            attributes={
                                "original_scan_id": original_id,
                                "assessment_scan_id": scan_id,
                                "candidate_sha256": case.archive_record["candidate_sha256"],
                            },
                        )
                    )
                    db.commit()
            output = {
                "case_id": case_id,
                "scan_id": scan_id,
                "match_status": result["match_status"],
            }
            results.append(output)
            print(json.dumps(output), flush=True)
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--revision", help="New idempotent run identifier for an explicit reassessment"
    )
    parser.add_argument("--comparison-kind", choices=["COPY", "CROP", "AI_EDIT"])
    parser.add_argument("--sightengine-timeout-seconds", type=float)
    arguments = parser.parse_args()
    settings = Settings()
    if arguments.sightengine_timeout_seconds is not None:
        settings = Settings.model_validate(
            {
                **settings.model_dump(),
                "sightengine_timeout_seconds": arguments.sightengine_timeout_seconds,
            }
        )
    refresh(settings, revision=arguments.revision, comparison_kind=arguments.comparison_kind)
