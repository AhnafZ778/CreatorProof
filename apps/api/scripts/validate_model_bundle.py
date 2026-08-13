from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.services.model_bundle import QUALIFICATION_STATES, load_model_bundle


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate a CreatorProof ModelBundle manifest and print its canonical identity."
    )
    parser.add_argument(
        "manifest",
        nargs="?",
        type=Path,
        default=Path("model_lab/bundles/creatorproof-runtime-ready-v1.json"),
    )
    parser.add_argument("--require-state", choices=QUALIFICATION_STATES)
    args = parser.parse_args()

    try:
        bundle = load_model_bundle(args.manifest, strict=True)
    except ValueError as exc:
        print(json.dumps({"valid": False, "error": str(exc)}, indent=2))
        return 2

    if args.require_state:
        actual_rank = QUALIFICATION_STATES.index(bundle.qualification_state)
        required_rank = QUALIFICATION_STATES.index(args.require_state)
        if actual_rank < required_rank:
            print(
                json.dumps(
                    {
                        "valid": True,
                        "requirement_met": False,
                        **bundle.status(),
                        "required_state": args.require_state,
                    },
                    indent=2,
                )
            )
            return 3
    print(json.dumps({"valid": True, "requirement_met": True, **bundle.status()}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
