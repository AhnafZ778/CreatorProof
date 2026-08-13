from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.services.benchmark_manifest import load_corpus_manifest, validate_manifest_set


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate CreatorProof corpus manifests, rights metadata, exposure state, and "
            "cross-partition source-lineage isolation."
        )
    )
    parser.add_argument("manifests", nargs="+", type=Path)
    args = parser.parse_args()
    try:
        report = validate_manifest_set([load_corpus_manifest(path) for path in args.manifests])
    except ValueError as exc:
        print(json.dumps({"valid": False, "error": str(exc)}, indent=2))
        return 2
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
