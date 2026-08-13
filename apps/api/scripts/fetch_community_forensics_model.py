from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fetch the official MIT-licensed Community Forensics safetensors model."
    )
    parser.add_argument(
        "--destination",
        type=Path,
        default=Path("models/community-forensics-384"),
    )
    parser.add_argument("--revision", default=None)
    parser.add_argument("--expected-sha256", default="")
    parser.add_argument("--metadata-output", type=Path)
    args = parser.parse_args()

    try:
        from huggingface_hub import HfApi, snapshot_download
    except ImportError as exc:
        raise SystemExit("Install requirements-synthetic.txt before fetching the model.") from exc

    destination = args.destination.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    snapshot_download(
        repo_id="OwensLab/commfor-model-384",
        revision=args.revision,
        local_dir=destination,
        allow_patterns=["*.safetensors", "config.json", "README.md"],
    )
    weights = sorted(destination.glob("*.safetensors"))
    if len(weights) != 1:
        raise SystemExit(f"Expected exactly one safetensors file, found {len(weights)}")
    actual_sha256 = _sha256(weights[0])
    expected_sha256 = args.expected_sha256.strip().lower()
    if expected_sha256 and actual_sha256 != expected_sha256:
        raise SystemExit(
            "Community Forensics artifact digest mismatch: "
            f"expected {expected_sha256}, got {actual_sha256}"
        )
    resolved_revision = (
        HfApi()
        .model_info(
            "OwensLab/commfor-model-384",
            revision=args.revision,
        )
        .sha
    )
    metadata = {
        "schema": "creatorproof.fetched_model_artifact.v1",
        "component_id": "origin-community-forensics",
        "provider": "community-forensics-vit-small-384",
        "repository": "OwensLab/commfor-model-384",
        "requested_revision": args.revision,
        "resolved_revision": resolved_revision,
        "destination": str(destination),
        "weights": weights[0].name,
        "artifact_sha256": actual_sha256,
        "expected_sha256": expected_sha256 or None,
        "digest_verified": bool(expected_sha256),
        "license": "MIT",
        "fetched_at": datetime.now(UTC).isoformat(),
        "runtime_calibration": "REQUIRED_FOR_DEPLOYMENT_DOMAIN",
    }
    if args.metadata_output:
        args.metadata_output.parent.mkdir(parents=True, exist_ok=True)
        args.metadata_output.write_text(
            json.dumps(metadata, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(metadata, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
