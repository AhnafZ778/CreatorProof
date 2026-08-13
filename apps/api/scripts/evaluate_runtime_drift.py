from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.services.drift_monitor import (
    aggregate_packet_telemetry,
    evaluate_runtime_drift,
    load_drift_baseline_registry,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate packet score summaries against authorized drift baselines."
    )
    parser.add_argument("packets_jsonl", type=Path)
    parser.add_argument(
        "--registry",
        type=Path,
        default=Path("model_lab/registries/drift-baselines.v1.json"),
    )
    args = parser.parse_args()
    try:
        packets = [
            json.loads(line)
            for line in args.packets_jsonl.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        registry = load_drift_baseline_registry(args.registry)
        aggregate = aggregate_packet_telemetry(packets)
        result = evaluate_runtime_drift(aggregate, registry)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(json.dumps({"valid": False, "error": str(exc)}, indent=2))
        return 2
    print(json.dumps({"aggregate": aggregate, "evaluation": result}, indent=2, sort_keys=True))
    if result["state"] == "NOT_CONFIGURED":
        return 3
    return 4 if result["revalidation_required"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
