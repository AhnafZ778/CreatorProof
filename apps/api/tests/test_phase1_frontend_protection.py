"""Preserve the historical backend-only Phase 1 frontend audit.

The subsequent, explicitly authorized frontend integration supersedes the source
freeze. Its behavior is checked by the frontend contracts and browser smoke test.
The original audit artifacts must still remain unchanged and internally consistent.
"""

import hashlib
import json
from pathlib import Path


def test_original_phase1_frontend_audit_is_preserved():
    root = Path(__file__).resolve().parents[3]
    baseline_bytes = (root / "docs/phase1-frontend-baseline.json").read_bytes()
    report_bytes = (root / "docs/phase1-frontend-verification.json").read_bytes()
    assert hashlib.sha256(baseline_bytes).hexdigest() == (
        "5cf5bc6bd059645e36f51e63bf35955eedde3d2a872d68c8fcd05afd1107413e"
    )
    assert hashlib.sha256(report_bytes).hexdigest() == (
        "f7029b61b0e5ad164da4c8b0b936e86e2a0fa0e10c48eedcc943cea709528bd7"
    )
    baseline = json.loads(baseline_bytes)
    report = json.loads(report_bytes)
    assert report["frontend_unchanged"] is True
    assert report["changed_files"] == []
    assert report["file_count"] == len(baseline["files"]) == 105
    assert report["baseline"] == "docs/phase1-frontend-baseline.json"
