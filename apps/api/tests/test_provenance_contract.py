import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from app.domain.enums import ProvenanceStatus
from app.providers.provenance import (
    C2PAOutputLimitError,
    C2PAToolProvenanceProvider,
    _json_within_budget,
    _run_bounded,
)


def _provider(monkeypatch):
    monkeypatch.setattr("app.providers.provenance.shutil.which", lambda _binary: "/bin/true")
    monkeypatch.setattr(
        "app.providers.provenance._run_bounded",
        lambda *args, **kwargs: _completed("c2patool test-version"),
    )
    return C2PAToolProvenanceProvider(
        "fake-c2patool",
        trust_policy_id="test-trust-policy-v1",
    )


def _completed(payload, *, returncode=0, stderr=""):
    stdout = payload if isinstance(payload, str) else json.dumps(payload)
    return subprocess.CompletedProcess(
        args=["fake-c2patool"],
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


def test_absent_manifest_is_neutral_and_not_human_origin_evidence(monkeypatch, tmp_path):
    provider = _provider(monkeypatch)
    monkeypatch.setattr(
        "app.providers.provenance._run_bounded",
        lambda *args, **kwargs: _completed("", returncode=1, stderr="Error: No claim found"),
    )

    result = provider.inspect(tmp_path / "image.png")

    assert result.status == ProvenanceStatus.NOT_PRESENT
    assert result.trust_details["manifest_present"] is False
    assert result.trust_details["signature_valid"] is None
    assert "ABSENCE_DOES_NOT_ESTABLISH_HUMAN_ORIGIN" in result.reason_codes


@pytest.mark.parametrize(
    "validity,bucket,expected",
    [
        ("claimSignature.insideValidity", "success", ProvenanceStatus.VALID_UNTRUSTED),
        ("claimSignature.insideValidity", "failure", ProvenanceStatus.INVALID),
        ("claimSignature.outsideValidity", "failure", ProvenanceStatus.INVALID),
    ],
)
def test_signature_validity_success_does_not_imply_failure_or_signer_trust(
    monkeypatch, tmp_path, validity, bucket, expected
):
    provider = _provider(monkeypatch)
    payload = {
        "active_manifest": "claim-1",
        "manifests": {"claim-1": {}},
        "validation_results": {
            "success": [{"code": "claimSignature.validated"}],
            "informational": [
                {"code": "signingCredential.untrusted"},
                {"code": "timeStamp.untrusted"},
            ],
        },
    }
    payload["validation_results"].setdefault(bucket, []).append({"code": validity})
    monkeypatch.setattr(
        "app.providers.provenance._run_bounded", lambda *args, **kwargs: _completed(payload)
    )
    result = provider.inspect(tmp_path / "image.png")
    assert result.status == expected
    assert result.trust_details["signer_trusted"] is not True


def test_valid_untrusted_ai_assertion_keeps_signature_and_trust_separate(
    monkeypatch,
    tmp_path,
):
    provider = _provider(monkeypatch)
    payload = {
        "active_manifest": "claim-1",
        "validation_status": [
            {"code": "claimSignature.validated"},
            {"code": "signingCredential.untrusted"},
        ],
        "manifests": {
            "claim-1": {
                "claim_generator": "example",
                "assertions": [
                    {
                        "label": "c2pa.actions",
                        "digitalSourceType": "trainedAlgorithmicMedia",
                    }
                ],
                "ingredients": [{"relationship": "parentOf"}],
            }
        },
    }
    monkeypatch.setattr(
        "app.providers.provenance._run_bounded",
        lambda *args, **kwargs: _completed(payload),
    )

    result = provider.inspect(tmp_path / "image.png")

    assert result.status == ProvenanceStatus.VALID_UNTRUSTED
    assert result.trust_details == {
        "manifest_present": True,
        "manifest_valid": True,
        "signature_valid": True,
        "signer_trusted": False,
        "signer_trust_state": "NOT_CONFIRMED",
        "relevant_ai_assertion_present": True,
        "ingredient_chain_state": "PRESENT",
        "trust_policy_id": "test-trust-policy-v1",
        "validation_tool": "c2patool-official",
    }
    assert "C2PA_GENERATIVE_AI_ACTION_ASSERTED" in result.reason_codes


def test_trusted_signer_is_explicit(monkeypatch, tmp_path):
    provider = _provider(monkeypatch)
    payload = {
        "active_manifest": "claim-1",
        "validation_results": {
            "activeManifest": {
                "success": [
                    {"code": "claimSignature.validated"},
                    {"code": "signingCredential.trusted"},
                ]
            }
        },
        "manifests": {"claim-1": {"claim_generator": "example"}},
    }
    monkeypatch.setattr(
        "app.providers.provenance._run_bounded",
        lambda *args, **kwargs: _completed(payload),
    )

    result = provider.inspect(tmp_path / "image.png")

    assert result.status == ProvenanceStatus.VALID_TRUSTED
    assert result.trust_details["signature_valid"] is True
    assert result.trust_details["signer_trusted"] is True
    assert result.trust_details["signer_trust_state"] == "TRUSTED"


def test_invalid_manifest_never_reports_valid_signature(monkeypatch, tmp_path):
    provider = _provider(monkeypatch)
    payload = {
        "active_manifest": "claim-1",
        "validation_results": {
            "activeManifest": {"failure": [{"code": "claimSignature.mismatch"}]}
        },
        "manifests": {"claim-1": {"validation": "arbitrary display text"}},
    }
    monkeypatch.setattr(
        "app.providers.provenance._run_bounded",
        lambda *args, **kwargs: _completed(payload, returncode=1),
    )

    result = provider.inspect(tmp_path / "image.png")

    assert result.status == ProvenanceStatus.INVALID
    assert result.trust_details["manifest_valid"] is False
    assert result.trust_details["signature_valid"] is False
    assert result.trust_details["signer_trusted"] is None


def test_arbitrary_manifest_text_cannot_forge_trust_or_invalidation(monkeypatch, tmp_path):
    provider = _provider(monkeypatch)
    payload = {
        "active_manifest": "claim-1",
        "manifests": {
            "claim-1": {
                "claim_generator": "valid_trusted invalid signature tampered",
                "assertions": [{"label": "example", "note": "trainedAlgorithmicMedia"}],
            }
        },
    }
    monkeypatch.setattr(
        "app.providers.provenance._run_bounded",
        lambda *args, **kwargs: _completed(payload),
    )

    result = provider.inspect(tmp_path / "image.png")

    assert result.status == ProvenanceStatus.VALID_UNTRUSTED
    assert result.trust_details["signer_trusted"] is False
    assert result.manifest_summary["ai_assertion_present"] is False


@pytest.mark.parametrize("stream", ["stdout", "stderr"])
def test_real_subprocess_capture_limit_is_enforced_on_each_pipe(stream):
    # An actual subprocess writes far beyond a tiny limit. This exercises pipe
    # draining/termination rather than mocking an already allocated result.
    started = time.monotonic()
    with pytest.raises(C2PAOutputLimitError):
        _run_bounded(
            [
                sys.executable,
                "-c",
                f"import sys; sys.{stream}.buffer.write(b'x' * 2_000_000); sys.{stream}.flush()",
            ],
            timeout=3,
            max_bytes=4096,
        )
    assert time.monotonic() - started < 3


def test_real_subprocess_stdout_stderr_share_capture_limit():
    with pytest.raises(C2PAOutputLimitError):
        _run_bounded(
            [
                sys.executable,
                "-c",
                "import os; os.write(1, b'a' * 3072); os.write(2, b'b' * 3072)",
            ],
            timeout=3,
            max_bytes=4096,
        )


def test_real_subprocess_exact_capture_limit_and_exit_status_are_preserved():
    result = _run_bounded(
        [
            sys.executable,
            "-c",
            "import os; os.write(1, b'a' * 2048); os.write(2, b'b' * 2048); raise SystemExit(7)",
        ],
        timeout=3,
        max_bytes=4096,
    )
    assert result.stdout == "a" * 2048
    assert result.stderr == "b" * 2048
    assert result.returncode == 7


def test_real_subprocess_timeout_is_bounded():
    started = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        _run_bounded(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            timeout=0.2,
            max_bytes=4096,
        )
    assert time.monotonic() - started < 3


@pytest.mark.skipif(os.name != "posix", reason="Linux process-group pipe cleanup")
def test_real_subprocess_timeout_kills_inherited_pipe_descendant(tmp_path):
    survivor = tmp_path / "survived"
    grandchild = (
        "import time; from pathlib import Path; time.sleep(0.7); "
        f"Path({str(survivor)!r}).write_text('should be killed')"
    )
    # The parent exits while its descendant holds both pipes open. Killing only
    # the already exited parent would leave the descendant running.
    script = f"import subprocess, sys; subprocess.Popen([sys.executable, '-c', {grandchild!r}])"
    with pytest.raises(subprocess.TimeoutExpired):
        _run_bounded([sys.executable, "-c", script], timeout=0.2, max_bytes=4096)
    time.sleep(0.8)
    assert not survivor.exists()


def test_inspection_uses_read_only_offline_settings_and_absolute_source(monkeypatch, tmp_path):
    provider = _provider(monkeypatch)

    def inspect(args, **kwargs):
        settings_path = Path(args[args.index("--settings") + 1])
        assert json.loads(settings_path.read_text()) == {
            "verify": {
                "remote_manifest_fetch": False,
                "ocsp_fetch": False,
                "verify_after_reading": True,
            }
        }
        assert "--detailed" in args
        assert Path(args[-1]).is_absolute()
        assert kwargs["timeout"] == provider.timeout_seconds
        return _completed({})

    monkeypatch.setattr("app.providers.provenance._run_bounded", inspect)
    assert (
        provider.inspect(tmp_path / "--malicious-option.png").status == ProvenanceStatus.NOT_PRESENT
    )


@pytest.mark.parametrize("signature_info", [None, "unexpected", ["unexpected"], 3, True])
def test_malformed_signature_info_never_crashes_projection(monkeypatch, tmp_path, signature_info):
    provider = _provider(monkeypatch)
    payload = {
        "active_manifest": "claim-1",
        "manifests": {"claim-1": {"signature_info": signature_info}},
    }
    monkeypatch.setattr(
        "app.providers.provenance._run_bounded",
        lambda *args, **kwargs: _completed(payload),
    )
    result = provider.inspect(tmp_path / "image.png")
    assert result.status == ProvenanceStatus.VALID_UNTRUSTED
    assert result.manifest_summary["signature_timestamp"] is None


def test_malformed_projection_fields_are_scalar_only_and_lists_are_bounded(monkeypatch, tmp_path):
    provider = _provider(monkeypatch)
    payload = {
        "active_manifest": "claim-1",
        "manifests": {
            "claim-1": {
                "claim_generator": {"private": "untrusted object"},
                "claim_version": [2],
                "signature_info": {"time": {"private": "untrusted object"}},
                "ingredients": [
                    {"title": {"private": "untrusted object"}, "relationship": ["parentOf"]}
                ]
                * 101,
                "assertions": [
                    {
                        "actions": [
                            {"action": ["bad"], "when": {"bad": True}, "digitalSourceType": 3}
                        ]
                        * 101
                    }
                ],
            }
        },
    }
    monkeypatch.setattr(
        "app.providers.provenance._run_bounded",
        lambda *args, **kwargs: _completed(payload),
    )
    summary = provider.inspect(tmp_path / "image.png").manifest_summary
    assert summary["signature_timestamp"] is None
    assert summary["claim_generator"] is None
    assert summary["c2pa_version"] is None
    assert len(summary["actions"]) == len(summary["ingredients"]) == 100
    assert summary["actions"][0] == {
        "action": "UNKNOWN",
        "when": None,
        "digital_source_type": None,
    }
    assert summary["ingredients"][0]["relationship"] == "INGREDIENT"
    assert "untrusted object" not in json.dumps(summary)


@pytest.mark.parametrize("payload", ["[" * 21 + "0" + "]" * 21, "[" + "0," * 50_001 + "0]"])
def test_excessive_json_structure_rejected_before_materialization(monkeypatch, tmp_path, payload):
    provider = _provider(monkeypatch)
    monkeypatch.setattr(
        "app.providers.provenance._run_bounded",
        lambda *args, **kwargs: _completed(payload),
    )

    def must_not_materialize(*args, **kwargs):
        raise AssertionError("json.loads must not run past structural limits")

    monkeypatch.setattr("app.providers.provenance.json.loads", must_not_materialize)
    result = provider.inspect(tmp_path / "image.png")
    assert result.status == ProvenanceStatus.ERROR
    assert result.reason_codes == ["C2PA_JSON_STRUCTURE_LIMIT"]
    assert result.trust_details["signer_trusted"] is None


def test_json_structure_budget_ignores_delimiters_inside_escaped_strings():
    assert _json_within_budget(json.dumps({"text": '\\"' + "[{,:" * 60_000}))


@pytest.mark.parametrize(
    "payload",
    [
        '{"validation_results":{"failure":[],"failure":[]}}',
        '{"claim_version":' + "9" * 5000 + "}",
        '{"claim_version":' + "9" * 129 + "}",
        '{"claim_version":NaN}',
        '{"claim_version":Infinity}',
    ],
)
def test_ambiguous_or_oversized_json_numbers_fail_closed(monkeypatch, tmp_path, payload):
    provider = _provider(monkeypatch)
    monkeypatch.setattr(
        "app.providers.provenance._run_bounded",
        lambda *args, **kwargs: _completed(payload),
    )
    result = provider.inspect(tmp_path / "image.png")
    assert result.status == ProvenanceStatus.ERROR
    assert result.reason_codes == ["C2PA_OUTPUT_NOT_JSON"]
    assert result.trust_details["manifest_valid"] is None


def test_output_limit_error_is_persistable_unknown_state(monkeypatch, tmp_path):
    provider = _provider(monkeypatch)

    def oversized(*args, **kwargs):
        raise C2PAOutputLimitError("bounded capture stopped")

    monkeypatch.setattr("app.providers.provenance._run_bounded", oversized)
    result = provider.inspect(tmp_path / "image.png")
    assert result.status == ProvenanceStatus.ERROR
    assert result.reason_codes == ["C2PA_OUTPUT_OVERSIZED"]
    assert result.trust_details["signature_valid"] is None
    assert result.trust_details["signer_trusted"] is None


def test_version_probe_has_separate_small_budget_and_overflow_disables_provider(monkeypatch):
    monkeypatch.setattr("app.providers.provenance.shutil.which", lambda _binary: "/bin/true")

    def oversized(args, **kwargs):
        assert args[-1] == "--version"
        assert kwargs["max_bytes"] == 16 * 1024
        raise C2PAOutputLimitError("identity output limit")

    monkeypatch.setattr("app.providers.provenance._run_bounded", oversized)
    provider = C2PAToolProvenanceProvider("fake-c2patool")
    assert not provider.available
    assert provider.unavailable_reason == "C2PATOOL_IDENTITY_OUTPUT_OVERSIZED"


def test_duplicate_validation_code_cannot_overwrite_failure(monkeypatch, tmp_path):
    provider = _provider(monkeypatch)
    payload = {
        "active_manifest": "claim-1",
        "manifests": {"claim-1": {}},
        "validation_results": {
            "failure": [{"code": "claimSignature.validated"}],
            "success": [{"code": "claimSignature.validated"}],
        },
    }
    monkeypatch.setattr(
        "app.providers.provenance._run_bounded",
        lambda *args, **kwargs: _completed(payload),
    )
    result = provider.inspect(tmp_path / "image.png")
    assert result.status == ProvenanceStatus.INVALID
    assert result.trust_details["manifest_valid"] is False
    assert result.trust_details["signature_valid"] is False
    assert result.trust_details["signer_trusted"] is None


@pytest.mark.parametrize("contradictory", [False, True])
def test_failed_or_contradictory_trust_markers_never_claim_trusted(
    monkeypatch, tmp_path, contradictory
):
    provider = _provider(monkeypatch)
    payload = {
        "active_manifest": "claim-1",
        "manifests": {"claim-1": {}},
        "validation_results": {
            "failure": [
                {
                    "code": "signingCredential.untrusted"
                    if contradictory
                    else "signingCredential.trusted"
                }
            ],
            "success": [
                {"code": "claimSignature.validated"},
                *([{"code": "signingCredential.trusted"}] if contradictory else []),
            ],
        },
    }
    monkeypatch.setattr(
        "app.providers.provenance._run_bounded",
        lambda *args, **kwargs: _completed(payload),
    )
    result = provider.inspect(tmp_path / "image.png")
    assert result.status == ProvenanceStatus.VALID_UNTRUSTED
    assert result.trust_details["signature_valid"] is True
    assert result.trust_details["signer_trusted"] is False
    if contradictory:
        assert "C2PA_SIGNER_TRUST_RESULTS_CONTRADICTORY" in result.reason_codes
