from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.services.benchmark_manifest import validate_benchmark_report_payload


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate a CreatorProof benchmark report and print its canonical digest."
    )
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    try:
        payload = json.loads(args.report.read_text(encoding="utf-8"))
        result = validate_benchmark_report_payload(payload)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(json.dumps({"valid": False, "error": str(exc)}, indent=2))
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
