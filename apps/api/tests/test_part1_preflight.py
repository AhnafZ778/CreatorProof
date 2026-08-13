import json
import subprocess
import sys


def test_default_part1_preflight_is_machine_readable_and_truthful():
    completed = subprocess.run(
        [sys.executable, "-m", "scripts.preflight_part1"],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stderr
    report = json.loads(completed.stdout)
    validation = report["model_bundle_validation"]
    assert report["schema"] == "creatorproof.part1_preflight.v1"
    assert report["valid"] is True
    assert validation["runtime_lock"]["matches"] is True
    assert validation["bundle"]["qualification_state"] == "RUNTIME_READY"
    assert validation["demo_ready"] is False
    assert "not an accuracy" in report["claim_boundary"]
