import json
import subprocess
import sys
import time
from io import BytesIO
from threading import Event

from fastapi.testclient import TestClient
from PIL import Image

import app.container as container_module
from app.core.config import Settings
from app.main import create_app
from app.providers.synthetic_detection import ExternalJsonSyntheticDetector
from app.services.jobs import LocalThreadJobQueue

LOCAL_SCAN_TEST_TIMEOUT_SECONDS = 10


def _png_bytes() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (96, 96), "#446688").save(buffer, format="PNG")
    return buffer.getvalue()


def test_external_detector_with_missing_executable_is_unavailable():
    detector = ExternalJsonSyntheticDetector(
        {
            "name": "missing-runtime",
            "command": "creatorproof-command-that-does-not-exist --manifest {manifest}",
        }
    )

    assert detector.available is False
    assert detector.unavailable_reason.startswith("EXTERNAL_DETECTOR_EXECUTABLE_NOT_FOUND")


def test_external_manifest_detector_spawns_once_for_all_views(monkeypatch):
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        manifest_path = command[command.index("--manifest") + 1]
        manifest = json.loads(open(manifest_path, encoding="utf-8").read())
        payload = {
            "results": [
                {
                    "id": item["id"],
                    "provider": "batch-test",
                    "score": 0.82,
                    "calibrated": False,
                }
                for item in manifest["items"]
            ]
        }
        return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")

    monkeypatch.setattr("app.providers.synthetic_detection.subprocess.run", fake_run)
    detector = ExternalJsonSyntheticDetector(
        {
            "name": "batch-test",
            "command": f"{sys.executable} adapter.py --manifest {{manifest}}",
            "timeout_seconds": 30,
            "evidence_family": "TEST_FAMILY",
        },
        maximum_timeout_seconds=30,
    )

    results = detector.predict_many([Image.new("RGB", (64, 64)) for _ in range(10)])

    assert len(calls) == 1
    assert len(results) == 10
    assert all(not isinstance(item, Exception) and item.score == 0.82 for item in results)
    assert calls[0][1]["timeout"] <= 30


def test_legacy_external_views_share_one_decreasing_deadline(monkeypatch):
    observed_timeouts = []

    def fake_run(command, **kwargs):
        del command
        observed_timeouts.append(float(kwargs["timeout"]))
        return subprocess.CompletedProcess(
            [],
            0,
            json.dumps({"provider": "legacy-test", "score": 0.7}),
            "",
        )

    monkeypatch.setattr("app.providers.synthetic_detection.subprocess.run", fake_run)
    detector = ExternalJsonSyntheticDetector(
        {
            "name": "legacy-test",
            "command": f"{sys.executable} adapter.py --image {{image}}",
            "timeout_seconds": 5,
        },
        maximum_timeout_seconds=5,
    )

    results = detector.predict_many([Image.new("RGB", (32, 32)) for _ in range(4)])

    assert len(results) == 4
    assert len(observed_timeouts) == 4
    assert observed_timeouts == sorted(observed_timeouts, reverse=True)
    assert max(observed_timeouts) <= 5


def test_local_thread_queue_enqueue_does_not_wait_for_callback():
    started = Event()
    release = Event()

    def callback(scan_id):
        assert scan_id == "scn_test"
        started.set()
        assert release.wait(timeout=2)

    queue = LocalThreadJobQueue(callback, max_workers=1)
    before = time.monotonic()
    queue.enqueue("scn_test")
    elapsed = time.monotonic() - before

    assert elapsed < 0.2
    assert started.wait(timeout=1)
    assert queue.healthy() is True
    release.set()
    queue.close()


def test_legacy_inline_setting_is_migrated_outside_tests(tmp_path):
    app = create_app(
        Settings(
            environment="development",
            database_url=f"sqlite:///{tmp_path / 'migration.db'}",
            storage_root=tmp_path / "objects",
            job_backend="inline",
            dev_api_key="migration-test-key",
            synthetic_detector="off",
            visible_ai_marker_mode="off",
        )
    )

    assert app.state.container.queue.name == "local-thread"
    app.state.container.queue.close()


def test_scan_post_returns_before_local_background_job_finishes(monkeypatch, tmp_path):
    started = Event()
    release = Event()

    def slow_process_scan(container, scan_id):
        del container, scan_id
        started.set()
        assert release.wait(timeout=3)

    monkeypatch.setattr(container_module, "process_scan", slow_process_scan)
    settings = Settings(
        environment="development",
        database_url=f"sqlite:///{tmp_path / 'runtime.db'}",
        storage_root=tmp_path / "objects",
        job_backend="local",
        dev_api_key="runtime-test-key",
        proof_log_path=tmp_path / "proof.jsonl",
        synthetic_detector="off",
        visible_ai_marker_mode="off",
    )
    app = create_app(settings)
    try:
        with TestClient(app) as client:
            before = time.monotonic()
            response = client.post(
                "/v1/scans",
                headers={
                    "X-API-Key": "runtime-test-key",
                    "Idempotency-Key": "runtime-nonblocking-001",
                },
                data={"catalog_id": "demo", "intended_use": "review"},
                files={"file": ("candidate.png", _png_bytes(), "image/png")},
            )
            elapsed = time.monotonic() - before
            assert response.status_code == 202
            assert elapsed < 0.5
            assert response.json()["state"] == "QUEUED"
            assert started.wait(timeout=1)
            release.set()
    finally:
        release.set()


def test_local_scan_persists_progress_and_completes(monkeypatch, tmp_path):
    settings = Settings(
        environment="development",
        database_url=f"sqlite:///{tmp_path / 'progress.db'}",
        storage_root=tmp_path / "objects",
        job_backend="local",
        dev_api_key="progress-test-key",
        proof_log_path=tmp_path / "proof.jsonl",
        synthetic_detector="off",
        visible_ai_marker_mode="off",
        c2pa_mode="off",
    )
    app = create_app(settings)
    container = app.state.container
    reached_source_check = Event()
    release_source_check = Event()
    original_inspect = container.provenance.inspect

    def controlled_inspect(path):
        reached_source_check.set()
        assert release_source_check.wait(timeout=3)
        return original_inspect(path)

    monkeypatch.setattr(container.provenance, "inspect", controlled_inspect)
    try:
        with TestClient(app) as client:
            response = client.post(
                "/v1/scans",
                headers={
                    "X-API-Key": "progress-test-key",
                    "Idempotency-Key": "runtime-progress-001",
                },
                data={"catalog_id": "demo", "intended_use": "review"},
                files={"file": ("candidate.png", _png_bytes(), "image/png")},
            )
            scan_id = response.json()["id"]
            assert reached_source_check.wait(timeout=1)

            progress_response = client.get(
                f"/v1/scans/{scan_id}",
                headers={"X-API-Key": "progress-test-key"},
            )
            progress_body = progress_response.json()
            assert progress_body["state"] == "PROCESSING"
            progress = progress_body["evidence_packet"]["progress"]
            assert progress["stage"] == "CHECKING_SOURCE"
            assert progress["label"] == "Checking source information"
            assert 0 < progress["percent"] < 100

            release_source_check.set()
            deadline = time.monotonic() + LOCAL_SCAN_TEST_TIMEOUT_SECONDS
            while time.monotonic() < deadline:
                completed = client.get(
                    f"/v1/scans/{scan_id}",
                    headers={"X-API-Key": "progress-test-key"},
                ).json()
                if completed["state"] == "COMPLETED":
                    break
                time.sleep(0.05)
            assert completed["state"] == "COMPLETED"
            assert completed["evidence_packet"]["schema"] == "creatorproof.evidence_packet.v1"
    finally:
        release_source_check.set()


def test_deferred_proof_failure_cannot_fail_completed_scan(tmp_path):
    class ExplodingProof:
        name = "test-exploding-proof"

        def anchor(self, packet_hash):
            del packet_hash
            raise RuntimeError("test proof outage")

        def status(self):
            return {
                "provider": self.name,
                "available": True,
                "scope": "TEST",
                "reason": None,
            }

    settings = Settings(
        environment="development",
        database_url=f"sqlite:///{tmp_path / 'proof-failure.db'}",
        storage_root=tmp_path / "objects",
        job_backend="local",
        dev_api_key="proof-test-key",
        synthetic_detector="off",
        visible_ai_marker_mode="off",
        c2pa_mode="off",
        sscd_model_path=tmp_path / "models" / "sscd-not-installed.pt",
    )
    app = create_app(settings)
    app.state.container.proof_anchor = ExplodingProof()
    app.state.container.blockchain.provider = app.state.container.proof_anchor
    with TestClient(app) as client:
        response = client.post(
            "/v1/scans",
            headers={
                "X-API-Key": "proof-test-key",
                "Idempotency-Key": "runtime-proof-failure-001",
            },
            data={"catalog_id": "demo", "intended_use": "review"},
            files={"file": ("candidate.png", _png_bytes(), "image/png")},
        )
        scan_id = response.json()["id"]
        deadline = time.monotonic() + LOCAL_SCAN_TEST_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            completed = client.get(
                f"/v1/scans/{scan_id}",
                headers={"X-API-Key": "proof-test-key"},
            ).json()
            if completed["state"] == "COMPLETED" and completed["anchor_status"] != "PENDING":
                break
            time.sleep(0.05)

    assert completed["state"] == "COMPLETED"
    assert completed["anchor_status"] == "FAILED"
    assert completed["evidence_packet"]["proof"]["receipt"]["error_code"].startswith(
        "PROOF_ANCHOR_FAILED"
    )
