"""Promotion-gated provider boundaries.

These classes intentionally fail closed instead of pretending research dependencies are
installed or licensed. The separate integration playbook contains the implementation and
benchmark prompts for each candidate.
"""


class CapabilityUnavailable(RuntimeError):
    pass


class LearnedLocalMatcherProvider:
    """Slot for XFeat/LightGlue/RoMa-family benchmark winners; SSCD is integrated elsewhere."""

    name = "learned-local-matcher-unconfigured"

    def __init__(self, model_path: str | None = None) -> None:
        if not model_path:
            raise CapabilityUnavailable(
                "A learned local matcher requires a pinned artifact plus "
                "CreatorProof benchmark calibration."
            )


class C2PAProvenanceProvider:
    name = "c2pa-unconfigured"

    def __init__(self) -> None:
        raise CapabilityUnavailable(
            "Enable only after pinning and testing the official C2PA SDK and trust configuration."
        )


class EASProofAnchor:
    name = "eas-unconfigured"

    def __init__(self) -> None:
        raise CapabilityUnavailable(
            "Enable only with an explicit network, schema, signer, retry, "
            "and revocation configuration."
        )
