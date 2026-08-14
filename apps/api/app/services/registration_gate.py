"""AI-origin screening on the enrollment path.

A CreatorProof catalog is the set of works a claimant asks the platform to treat
as theirs, and every later scan measures candidates against it. That makes the
catalog only as trustworthy as what is allowed into it: an AI-generated image
registered as a protected reference would let its registrant collect matches
against other people's work.

So the same origin lane the scan pipeline runs also runs here, and `BLOCK`
refuses the file when the AI signal is strong enough to stand on its own.
Three limits are deliberate:

  * The bar is a *score*, not a mood. Anything at or below
    `registration_origin_block_score` is admitted even when a detector raised an
    indicator, because a weak or contested signal is not grounds to turn an
    artist away from their own catalog. Only a score above the line refuses.
  * Only a *finding* refuses. `ORIGIN_UNKNOWN` and `CHECK_UNAVAILABLE` mean the
    checks produced no answer, and treating the absence of a result as a result
    would lock real artists out of their own catalog — the exact harm this gate
    exists to prevent.
  * A refusal is a statement about what this catalog will vouch for, never a
    finding about the person submitting. The message says what was observed and
    the full analysis is returned with it, so the claim can be contested.

Signed provenance asserting AI generation is the one case that refuses without a
score: there the file states its own origin, and no pixel measurement overrides
that.
"""

from __future__ import annotations

import logging
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

from PIL import Image

from app.container import Container
from app.domain.enums import RegistrationOriginGate
from app.services.synthetic_analysis import analyze_synthetic_origin

logger = logging.getLogger("creatorproof.registration_gate")

REFUSAL_CODE = "WORK_REGISTRATION_REFUSED_AI_ORIGIN"

# Presentation states that carry an affirmative AI finding. Reaching one of
# these is necessary to refuse but not sufficient: the score still has to clear
# the configured line. Anything absent from this set is either a quiet result or
# no result at all, and neither may refuse a registration.
_SCORED_FINDING_STATES = frozenset({"AI_INDICATORS_FOUND", "AI_INDICATORS_NEED_REVIEW"})

# Signed Content Credentials asserting AI generation. This is the file
# describing itself, so it refuses on its own without reference to the score.
_DECLARED_AI_STATE = "AI_CONFIRMED"


@dataclass(frozen=True)
class OriginGateOutcome:
    """What the gate observed, and whether the registration may proceed."""

    mode: RegistrationOriginGate
    checked: bool
    allowed: bool
    state: str
    classification: str
    evidence_tier: str
    headline: str
    summary: str
    reason: str
    analysis: dict
    score: float | None = None
    threshold: float | None = None

    def record(self) -> dict:
        """The compact verdict stored on the work.

        The full analysis is deliberately not persisted: it is large, it embeds
        provider runtimes that make rows non-comparable, and the durable claim
        here is only what the gate concluded. The score and the line it was
        measured against are kept, because a later reader cannot re-derive why
        this work was admitted without them.
        """
        return {
            "schema": "creatorproof.registration_origin_gate.v1",
            "mode": str(self.mode),
            "checked": self.checked,
            "allowed": self.allowed,
            "state": self.state,
            "classification": self.classification,
            "evidence_tier": self.evidence_tier,
            "headline": self.headline,
            "summary": self.summary,
            "score": self.score,
            "threshold": self.threshold,
        }


def _skipped(mode: RegistrationOriginGate, reason: str) -> OriginGateOutcome:
    return OriginGateOutcome(
        mode=mode,
        checked=False,
        allowed=True,
        state="NOT_CHECKED",
        classification="AI_ORIGIN_CHECK_NOT_RUN",
        evidence_tier="UNAVAILABLE",
        headline="AI-origin screening did not run",
        summary=reason,
        reason=reason,
        analysis={},
    )


def screen_registration_origin(
    container: Container,
    *,
    raw: bytes,
    image: Image.Image,
    filename: str = "reference.bin",
) -> OriginGateOutcome:
    """Run the origin lane over a work being registered.

    Never raises: a screening failure is reported as "not checked" and the
    registration proceeds. Refusing a real artist because a detector timed out
    would be a worse failure than admitting an unscreened file, which every
    later scan still evaluates on its own evidence.
    """
    mode = container.settings.registration_origin_gate
    if mode == RegistrationOriginGate.OFF:
        return _skipped(mode, "AI-origin screening is switched off for this deployment.")

    try:
        visible_marker = asdict(container.visible_markers.inspect(image))
    except Exception:
        logger.warning("visible-marker inspection failed during registration", exc_info=True)
        visible_marker = None

    # `provenance.inspect` reads a file, and registration has not written the
    # bytes to object storage yet, so the check gets its own short-lived copy.
    provenance = None
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as handle:
            handle.write(raw)
            temp_path = Path(handle.name)
        provenance = container.provenance.inspect(temp_path)
    except Exception:
        logger.warning("provenance inspection failed during registration", exc_info=True)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)

    if provenance is None:
        return _skipped(mode, "The origin checks could not be prepared for this file.")

    try:
        analysis = analyze_synthetic_origin(
            image=image,
            detector_router=container.synthetic_detection,
            provenance=provenance,
            settings=container.settings,
            visible_marker=visible_marker,
            source_media=raw,
            source_filename=filename,
        )
    except Exception:
        logger.warning("origin analysis failed during registration", exc_info=True)
        return _skipped(mode, "The AI-origin analysis did not complete for this file.")

    presentation = analysis.get("presentation") or {}
    state = str(presentation.get("state") or "ORIGIN_UNKNOWN").upper()
    threshold = container.settings.registration_origin_block_score
    score = _score(analysis)
    blocking_reason = _refusal_reason(state, score, threshold)
    allowed = blocking_reason is None or mode != RegistrationOriginGate.BLOCK

    return OriginGateOutcome(
        mode=mode,
        checked=True,
        allowed=allowed,
        state=state,
        classification=str(analysis.get("classification") or "AI_ORIGIN_UNKNOWN"),
        evidence_tier=str(analysis.get("evidence_tier") or "INCONCLUSIVE"),
        headline=str(presentation.get("headline") or "Origin analysis completed"),
        summary=str(presentation.get("summary") or ""),
        reason=blocking_reason or _admission_reason(state, score, threshold),
        score=score,
        threshold=threshold,
        analysis=analysis,
    )


def _score(analysis: dict) -> float | None:
    """The ensemble AI signal, or None when no detector returned one.

    A missing score is not a zero. No reading means the gate has nothing to
    measure against the threshold, and an unmeasured file is admitted.
    """
    raw = analysis.get("fused_detector_score")
    if isinstance(raw, bool) or not isinstance(raw, int | float):
        return None
    return float(raw)


def _refusal_reason(state: str, score: float | None, threshold: float) -> str | None:
    """Why this file may not enter the catalog, or None if it may."""
    if state == _DECLARED_AI_STATE:
        return "The file carries signed Content Credentials that assert AI generation."
    if state not in _SCORED_FINDING_STATES or score is None:
        return None
    if score <= threshold:
        return None
    return (
        f"AI-generation indicators scored {score:.0%}, above the "
        f"{threshold:.0%} limit this catalog accepts."
    )


def _admission_reason(state: str, score: float | None, threshold: float) -> str:
    """Why this file was allowed through, in the gate's own words."""
    if state in _SCORED_FINDING_STATES and score is not None:
        return (
            f"AI-generation indicators scored {score:.0%}, at or below the "
            f"{threshold:.0%} limit, so the work was admitted."
        )
    return "No AI-origin finding stood in the way of registration."
