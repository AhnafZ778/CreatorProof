import json
import subprocess

from app.domain.enums import ProvenanceStatus
from app.providers.provenance import C2PAToolProvenanceProvider


def _provider(monkeypatch):
    monkeypatch.setattr("app.providers.provenance.shutil.which", lambda _binary: "/bin/true")
    monkeypatch.setattr(
        "app.providers.provenance.subprocess.run",
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
        "app.providers.provenance.subprocess.run",
        lambda *args, **kwargs: _completed("", returncode=1, stderr="Error: No claim found"),
    )

    result = provider.inspect(tmp_path / "image.png")

    assert result.status == ProvenanceStatus.NOT_PRESENT
    assert result.trust_details["manifest_present"] is False
    assert result.trust_details["signature_valid"] is None
    assert "ABSENCE_DOES_NOT_ESTABLISH_HUMAN_ORIGIN" in result.reason_codes


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
        "app.providers.provenance.subprocess.run",
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
        "app.providers.provenance.subprocess.run",
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
        "app.providers.provenance.subprocess.run",
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
        "app.providers.provenance.subprocess.run",
        lambda *args, **kwargs: _completed(payload),
    )

    result = provider.inspect(tmp_path / "image.png")

    assert result.status == ProvenanceStatus.VALID_UNTRUSTED
    assert result.trust_details["signer_trusted"] is False
    assert result.manifest_summary["ai_assertion_present"] is False
