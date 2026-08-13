from __future__ import annotations

import argparse
import json
import mimetypes
import time
from pathlib import Path
from uuid import uuid4

import httpx


def _progress(body: dict) -> dict | None:
    packet = body.get("evidence_packet")
    if not isinstance(packet, dict):
        return None
    progress = packet.get("progress")
    return progress if isinstance(progress, dict) else None


def _run(args: argparse.Namespace) -> tuple[int, dict]:
    image_path = args.image.resolve()
    if not image_path.is_file():
        return 2, {"error_code": "INPUT_IMAGE_NOT_FOUND", "path": str(image_path)}
    api_url = args.api_url.rstrip("/")
    headers = {
        "X-API-Key": args.api_key,
        "Idempotency-Key": f"latency-{uuid4().hex}",
    }
    mime = mimetypes.guess_type(image_path.name)[0] or "application/octet-stream"
    accepted_started = time.perf_counter()
    with httpx.Client(timeout=args.request_timeout_seconds) as client:
        with image_path.open("rb") as image_handle:
            response = client.post(
                f"{api_url}/v1/scans",
                headers=headers,
                data={"catalog_id": args.catalog_id, "intended_use": args.intended_use},
                files={"file": (image_path.name, image_handle, mime)},
            )
        acceptance_seconds = time.perf_counter() - accepted_started
        try:
            body = response.json()
        except json.JSONDecodeError:
            body = {"raw_response": response.text[:500]}
        if response.status_code != 202 or not isinstance(body, dict) or not body.get("id"):
            return 2, {
                "error_code": "SCAN_NOT_ACCEPTED",
                "http_status": response.status_code,
                "acceptance_latency_ms": round(acceptance_seconds * 1000, 3),
                "response": body,
            }

        scan_id = str(body["id"])
        timeline = []
        last_stage = None
        processing_started = time.perf_counter()
        deadline = processing_started + args.max_wait_seconds
        while True:
            progress = _progress(body)
            if progress and progress.get("stage") != last_stage:
                last_stage = progress.get("stage")
                timeline.append(
                    {
                        "elapsed_ms": round((time.perf_counter() - processing_started) * 1000, 3),
                        "stage": progress.get("stage"),
                        "label": progress.get("label"),
                        "percent": progress.get("percent"),
                    }
                )
            if body.get("state") in {"COMPLETED", "FAILED"}:
                break
            if time.perf_counter() >= deadline:
                return 3, {
                    "schema": "creatorproof.scan_latency.v1",
                    "scan_id": scan_id,
                    "state": body.get("state"),
                    "acceptance_latency_ms": round(acceptance_seconds * 1000, 3),
                    "timed_out_after_seconds": args.max_wait_seconds,
                    "stage_timeline": timeline,
                    "verdict": "TARGET_MACHINE_SCAN_TIMEOUT",
                }
            poll_after_ms = int(progress.get("poll_after_ms") or 750) if progress else 750
            time.sleep(min(max(poll_after_ms / 1000, 0.25), 2.0))
            poll = client.get(
                f"{api_url}/v1/scans/{scan_id}",
                headers={"X-API-Key": args.api_key},
                timeout=10,
            )
            poll.raise_for_status()
            body = poll.json()

    total_seconds = acceptance_seconds + (time.perf_counter() - processing_started)
    packet = body.get("evidence_packet") if isinstance(body.get("evidence_packet"), dict) else {}
    synthetic = (
        packet.get("synthetic_origin") if isinstance(packet.get("synthetic_origin"), dict) else {}
    )
    return (0 if body.get("state") == "COMPLETED" else 2), {
        "schema": "creatorproof.scan_latency.v1",
        "scan_id": scan_id,
        "state": body.get("state"),
        "acceptance_latency_ms": round(acceptance_seconds * 1000, 3),
        "background_processing_ms": round(
            (time.perf_counter() - processing_started) * 1000,
            3,
        ),
        "total_latency_ms": round(total_seconds * 1000, 3),
        "stage_timeline": timeline,
        "synthetic_runtime": synthetic.get("runtime"),
        "anchor_status": body.get("anchor_status"),
        "error_code": body.get("error_code"),
        "verdict": "COMPLETED" if body.get("state") == "COMPLETED" else "SCAN_FAILED",
        "claim_boundary": (
            "This is target-machine latency, not a model-accuracy or production-SLA result."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Measure CreatorProof request acceptance and background scan latency."
    )
    parser.add_argument("image", type=Path)
    parser.add_argument("--api-url", default="http://localhost:8000")
    parser.add_argument("--api-key", default="change-me-before-sharing")
    parser.add_argument("--catalog-id", default="demo-catalog")
    parser.add_argument("--intended-use", default="latency/audit")
    parser.add_argument("--request-timeout-seconds", type=float, default=35.0)
    parser.add_argument("--max-wait-seconds", type=float, default=240.0)
    args = parser.parse_args()
    try:
        status, payload = _run(args)
    except (httpx.HTTPError, OSError, ValueError) as exc:
        status, payload = 2, {"error_code": f"{type(exc).__name__}:{exc}"}
    print(json.dumps(payload, indent=2, sort_keys=True))
    return status


if __name__ == "__main__":
    raise SystemExit(main())
