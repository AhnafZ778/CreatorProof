import json
from pathlib import Path

from app.services.model_bundle import load_model_bundle

REGISTRY_ROOT = Path("model_lab/registries")


def _load(name):
    return json.loads((REGISTRY_ROOT / name).read_text(encoding="utf-8"))


def test_terms_registry_covers_every_model_bundle_component():
    bundle = load_model_bundle(
        Path("model_lab/bundles/creatorproof-runtime-ready-v1.json"),
        strict=True,
    )
    registry = _load("dependency-terms.v1.json")

    assert registry["legal_approval_state"] == "NOT_LEGAL_ADVICE_REQUIRES_OWNER_APPROVAL"
    assert {record["component_id"] for record in registry["records"]} == {
        component.component_id for component in bundle.components
    }


def test_no_model_is_silently_promoted_or_claimed_calibrated():
    promotions = _load("promotion-records.v1.json")
    calibration = _load("calibration-registry.v1.json")

    assert promotions["records"] == []
    assert all(
        record["state"] == "NOT_CALIBRATED_FOR_TARGET_DOMAIN" for record in calibration["records"]
    )
