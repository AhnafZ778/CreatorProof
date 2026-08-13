from __future__ import annotations

import argparse
import hashlib
import json
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
    args = parser.parse_args()

    try:
        from huggingface_hub import snapshot_download
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
    print(
        json.dumps(
            {
                "provider": "community-forensics-vit-small-384",
                "repository": "OwensLab/commfor-model-384",
                "destination": str(destination),
                "weights": weights[0].name,
                "sha256": _sha256(weights[0]),
                "license": "MIT",
                "runtime_calibration": "REQUIRED_FOR_DEPLOYMENT_DOMAIN",
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
