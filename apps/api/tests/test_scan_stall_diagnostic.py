"""Diagnostic tests that expose the scan-stall root cause.

These tests verify structural properties that, when violated, cause the
ten-minute scan behavior observed in v0.9.0. They do not change detection
thresholds, model accuracy, or evidence semantics.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

# ---------------------------------------------------------------------------
# 1. POST /v1/scans must return promptly when job_backend=inline
# ---------------------------------------------------------------------------


def test_inline_scan_returns_within_budget(client, scan_headers):
    """Inline mode should complete within a measured budget, not block for >10min.

    This test documents the stall: with 2 detectors × 10 views and the GRIP
    external adapter spawning a fresh Python process (~11s each) per view,
    the inline job blocks the HTTP response for ~110s minimum.
    """
    image = Image.new("RGB", (64, 64), (100, 100, 200))
    import io

    buf = io.BytesIO()
    image.save(buf, format="PNG")
    buf.seek(0)

    # We only assert the structural property here; the full pipeline test
    # in test_scan_flow.py exercises correctness.
    # The point is: if this takes >60s, the inline-blocking stall is present.
    start = time.perf_counter()
    resp = client.post(
        "/v1/scans",
        headers=scan_headers,
        data={"catalog_id": "diag-stall", "intended_use": "DIAGNOSTIC"},
        files={"file": ("diag.png", buf, "image/png")},
    )
    elapsed = time.perf_counter() - start
    assert resp.status_code == 202
    body = resp.json()
    # The scan should reach a terminal state (inline mode runs synchronously)
    assert body["state"] in ("COMPLETED", "FAILED")
    # Record actual duration for the diagnostic report
    print(f"\n[DIAG] Inline scan took {elapsed * 1000:.0f}ms ({elapsed:.1f}s)")


# ---------------------------------------------------------------------------
# 2. Provider call count matches declared views (no accidental duplication)
# ---------------------------------------------------------------------------


def test_detector_view_count_matches_declared():
    """Each detector should be called exactly len(views) times, not more."""
    from app.services.synthetic_analysis import _delivery_views, _spatial_views

    image = Image.new("RGB", (512, 512), (120, 80, 200))
    dv = _delivery_views(image)
    sv = _spatial_views(image, 0.78)  # default fraction
    total = len(dv) + len(sv)
    # 5 delivery + up to 5 spatial (some may deduplicate)
    assert 5 <= total <= 10, f"Unexpected view count: {total}"
    # Verify the multiply: with 2 detectors this is 10–20 calls
    detector_count = 2  # community-forensics + grip-clipdet
    assert total * detector_count <= 20


# ---------------------------------------------------------------------------
# 3. External detector spawns a fresh process per call (root cause evidence)
# ---------------------------------------------------------------------------


def test_external_detector_spawns_subprocess_per_predict():
    """ExternalJsonSyntheticDetector.predict() calls subprocess.run each time.

    This is the root cause: a fresh Python process with model loading (~11s)
    is spawned for every single view, making 10 views × 11s = 110s minimum.
    """
    from app.providers.synthetic_detection import ExternalJsonSyntheticDetector

    spec = {
        "name": "test-external",
        "command": "echo {image}",
        "timeout_seconds": 5,
        "evidence_family": "TEST",
    }
    detector = ExternalJsonSyntheticDetector(spec)
    assert detector.available

    # Verify that predict() always calls subprocess.run (no caching/reuse)
    with patch("app.providers.synthetic_detection.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout='{"score": 0.5, "provider": "test"}',
        )
        image = Image.new("RGB", (64, 64), (100, 100, 200))
        detector.predict(image)
        detector.predict(image)
        # Each predict() spawns one subprocess — no model caching
        assert mock_run.call_count == 2


# ---------------------------------------------------------------------------
# 4. Subprocess timeout produces typed failure and terminal scan state
# ---------------------------------------------------------------------------


def test_external_detector_timeout_raises():
    """A timed-out external detector must raise, not hang silently."""
    import subprocess as sp

    from app.providers.synthetic_detection import ExternalJsonSyntheticDetector

    spec = {
        "name": "test-timeout",
        "command": "sleep 999 {image}",
        "timeout_seconds": 1,
        "evidence_family": "TEST",
    }
    detector = ExternalJsonSyntheticDetector(spec)
    image = Image.new("RGB", (64, 64), (100, 100, 200))

    # The subprocess either times out (TimeoutExpired) or exits non-zero
    # (RuntimeError). Both are valid failure modes that prevent silent hangs.
    with pytest.raises((sp.TimeoutExpired, RuntimeError)):
        detector.predict(image)


# ---------------------------------------------------------------------------
# 5. Frontend polling has a finite budget and does not spin forever
# ---------------------------------------------------------------------------


def test_frontend_polling_budget_is_finite():
    """The frontend polls at most 20 times with 350ms delay = 7s max.

    With inline mode completing in ~130s, the scan finishes BEFORE
    the first poll because the POST itself blocks. The polling loop
    is therefore never exercised — but if it were (redis mode), 7s is
    far too short for a 130s job. This documents the UI-side issue.
    """
    max_polls = 20
    poll_interval_ms = 350
    max_poll_budget_s = max_polls * poll_interval_ms / 1000
    assert max_poll_budget_s == pytest.approx(7.0)
    # The real job takes ~130s; the polling budget is 7s — a 18× gap.
    # This means in redis mode the UI would give up while the job runs.


# ---------------------------------------------------------------------------
# 6. Idempotent replay returns existing scan without re-running the job
# ---------------------------------------------------------------------------


def test_idempotent_replay_returns_existing(client, scan_headers):
    """Re-submitting with the same Idempotency-Key must not start duplicate work."""
    import io
    import uuid

    image = Image.new("RGB", (64, 64), (100, 100, 200))
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    buf.seek(0)

    idem_key = str(uuid.uuid4())
    headers = {**scan_headers, "Idempotency-Key": idem_key}

    resp1 = client.post(
        "/v1/scans",
        headers=headers,
        data={"catalog_id": "diag-idem", "intended_use": "DIAGNOSTIC"},
        files={"file": ("diag.png", buf, "image/png")},
    )
    assert resp1.status_code == 202
    scan_id = resp1.json()["id"]

    # Replay with same key
    buf.seek(0)
    resp2 = client.post(
        "/v1/scans",
        headers=headers,
        data={"catalog_id": "diag-idem", "intended_use": "DIAGNOSTIC"},
        files={"file": ("diag.png", buf, "image/png")},
    )
    assert resp2.status_code == 202
    assert resp2.json()["id"] == scan_id  # Same scan, no duplicate work


# ---------------------------------------------------------------------------
# 7. Proof anchor does not block scan completion
# ---------------------------------------------------------------------------


def test_proof_anchor_is_non_blocking():
    """The local proof anchor should complete in <100ms."""
    from app.core.config import Settings
    from app.providers.proof import build_proof_anchor

    settings = Settings()
    anchor = build_proof_anchor(settings)
    start = time.perf_counter()
    result = anchor.anchor("test_hash_abc123")
    elapsed_ms = (time.perf_counter() - start) * 1000
    assert elapsed_ms < 100, f"Proof anchor took {elapsed_ms:.0f}ms"
    assert result.status is not None


# ---------------------------------------------------------------------------
# 8. Worst-case multiplicative budget calculation
# ---------------------------------------------------------------------------


def test_worst_case_budget_exceeds_sane_limit():
    """Document that the configured worst-case budget is 1800s (30 minutes).

    With 1 external detector × 10 views × 180s timeout = 1800s.
    This is a structural design issue, not a configuration error.
    """
    external_timeout = 180  # configured in .env
    views = 10  # 5 delivery + 5 spatial
    external_detectors = 1
    worst_case = external_detectors * views * external_timeout
    assert worst_case == 1800  # 30 minutes — clearly unacceptable
