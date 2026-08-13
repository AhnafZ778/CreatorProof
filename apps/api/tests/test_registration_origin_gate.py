"""The enrollment AI-origin gate.

The cases that matter are the ones where a wrong answer causes real harm rather
than a cosmetic slip. Refusing a file the checks could not read would lock an
artist out of their own catalog, and admitting a file the checks positively
identified as AI-generated would let its registrant collect matches against
other people's work. Both directions are pinned here.
"""

from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from app.container import Container
from app.core.config import Settings
from app.domain.enums import RegistrationOriginGate
from app.main import create_app
from app.services import registration_gate
from app.services.registration_gate import (
    REFUSAL_CODE,
    OriginGateOutcome,
    screen_registration_origin,
)


def _image(seed: int = 0) -> bytes:
    image = Image.new("RGB", (320, 240), (245, 246, 248))
    draw = ImageDraw.Draw(image)
    draw.rectangle((30 + seed, 30, 145 + seed, 155), fill=(20, 105, 220))
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _settings(tmp_path, api_key: str, gate: RegistrationOriginGate) -> Settings:
    return Settings(
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'gate.db'}",
        storage_root=tmp_path / "objects",
        job_backend="inline",
        dev_api_key=api_key,
        proof_log_path=tmp_path / "proof-log.jsonl",
        proof_anchor_mode="none",
        sscd_model_path=tmp_path / "models" / "sscd-not-installed.pt",
        style_provider="diagnostic",
        synthetic_detector="off",
        synthetic_policy_mode="INFORMATIONAL",
        c2pa_mode="off",
        visible_ai_marker_mode="off",
        copy_retrieval_requirement="BASELINE_ALLOWED",
        registration_origin_gate=gate,
    )


def _register(client: TestClient, api_key: str, *, title: str = "Harbour study"):
    return client.post(
        "/v1/works",
        headers={"X-API-Key": api_key},
        data={"title": title, "catalog_id": "artist-library", "claimant": "A. Maker"},
        files={"file": ("work.png", _image(), "image/png")},
    )


def _outcome(state: str, *, mode=RegistrationOriginGate.BLOCK) -> OriginGateOutcome:
    """A screening result shaped like the real one, with only the state varied."""
    blocking = state in {"AI_CONFIRMED", "AI_INDICATORS_FOUND", "AI_INDICATORS_NEED_REVIEW"}
    return OriginGateOutcome(
        mode=mode,
        checked=True,
        allowed=not blocking or mode != RegistrationOriginGate.BLOCK,
        state=state,
        classification="AI_ORIGIN_MARKER_FOUND" if blocking else "NO_AI_ORIGIN_EVIDENCE_DETECTED",
        evidence_tier="REVIEW" if blocking else "INCONCLUSIVE",
        headline="A visible AI label was found" if blocking else "No strong AI signal",
        summary="",
        reason="Test reason." if blocking else "No AI-origin finding.",
        analysis={},
    )


@pytest.fixture
def gated(tmp_path, api_key, monkeypatch):
    """A client whose gate verdict the test chooses, keyed by presentation state."""

    def build(state: str, *, mode=RegistrationOriginGate.BLOCK) -> TestClient:
        monkeypatch.setattr(
            "app.api.routes.works.screen_registration_origin",
            lambda container, **kwargs: _outcome(state, mode=mode),
        )
        app = create_app(_settings(tmp_path, api_key, mode))
        return TestClient(app)

    return build


@pytest.mark.parametrize(
    "state",
    ["AI_CONFIRMED", "AI_INDICATORS_FOUND", "AI_INDICATORS_NEED_REVIEW"],
)
def test_an_ai_origin_finding_refuses_the_registration(gated, api_key, state):
    with gated(state) as client:
        response = _register(client, api_key)

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == REFUSAL_CODE
    assert detail["origin_state"] == state
    # The refusal has to stay a statement about the catalog, not about the person.
    assert "not a determination that a person did not create the work" in detail["boundary"]


@pytest.mark.parametrize("state", ["ORIGIN_UNKNOWN", "CHECK_UNAVAILABLE", "NO_STRONG_AI_SIGNAL"])
def test_the_absence_of_a_finding_never_refuses_a_registration(gated, api_key, state):
    # The single most damaging failure mode: an artist locked out of their own
    # catalog because a detector was missing, slow, or simply unsure.
    with gated(state) as client:
        response = _register(client, api_key)

    assert response.status_code == 201, response.text


def test_a_refused_file_leaves_nothing_behind(gated, api_key):
    with gated("AI_INDICATORS_FOUND") as client:
        assert _register(client, api_key).status_code == 422
        listing = client.get(
            "/v1/works",
            headers={"X-API-Key": api_key},
            params={"catalog_id": "artist-library"},
        )

    assert listing.status_code == 200
    assert listing.json() == []


def test_flag_only_records_the_finding_and_still_registers(gated, api_key):
    with gated("AI_INDICATORS_FOUND", mode=RegistrationOriginGate.FLAG_ONLY) as client:
        response = _register(client, api_key)

    assert response.status_code == 201, response.text
    assessment = response.json()["origin_assessment"]
    assert assessment["allowed"] is True
    assert assessment["state"] == "AI_INDICATORS_FOUND"
    assert assessment["mode"] == "FLAG_ONLY"


def test_a_clean_registration_records_what_was_screened(gated, api_key):
    with gated("NO_STRONG_AI_SIGNAL") as client:
        response = _register(client, api_key)

    assessment = response.json()["origin_assessment"]
    assert assessment["checked"] is True
    assert assessment["state"] == "NO_STRONG_AI_SIGNAL"
    assert assessment["schema"] == "creatorproof.registration_origin_gate.v1"


def test_switching_the_gate_off_skips_the_check_entirely(tmp_path, api_key, monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(
        registration_gate,
        "analyze_synthetic_origin",
        lambda **kwargs: calls.append("ran") or {},
    )
    settings = _settings(tmp_path, api_key, RegistrationOriginGate.OFF)
    with TestClient(create_app(settings)) as client:
        response = _register(client, api_key)

    assert response.status_code == 201
    assert calls == []
    # Off is not the same as screened-and-quiet, so nothing is recorded.
    assert response.json()["origin_assessment"] is None


def test_a_screening_failure_admits_the_file_rather_than_refusing_it(tmp_path, api_key):
    """A detector that raises must not become a refusal."""

    class Exploding:
        name = "exploding-detector"

        def inspect(self, *args, **kwargs):
            raise RuntimeError("detector exploded")

    settings = _settings(tmp_path, api_key, RegistrationOriginGate.BLOCK)
    app = create_app(settings)
    container: Container = app.state.container
    object.__setattr__(container, "provenance", Exploding())

    outcome = screen_registration_origin(
        container,
        raw=_image(),
        image=Image.open(BytesIO(_image())),
    )
    assert outcome.allowed is True
    assert outcome.checked is False
