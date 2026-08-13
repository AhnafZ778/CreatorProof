from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.services.model_acceptance import (
    evaluate_benchmark_acceptance,
    load_acceptance_policy,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate a sealed report against a preregistered policy without promotion."
    )
    parser.add_argument("report", type=Path)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument(
        "--external-evidence",
        type=Path,
        help="Optional JSON object mapping external gate IDs to approval references.",
    )
    args = parser.parse_args()
    try:
        report = json.loads(args.report.read_text(encoding="utf-8"))
        policy = load_acceptance_policy(args.policy)
        external = (
            json.loads(args.external_evidence.read_text(encoding="utf-8"))
            if args.external_evidence
            else None
        )
        if external is not None and not isinstance(external, dict):
            raise ValueError("external evidence must be a JSON object")
        result = evaluate_benchmark_acceptance(
            report=report,
            policy=policy,
            external_evidence=external,
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(json.dumps({"valid": False, "error": str(exc)}, indent=2))
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["ready_for_human_promotion_review"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
