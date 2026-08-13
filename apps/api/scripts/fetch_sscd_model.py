"""Fetch the official SSCD DISC mixup TorchScript inference artifact.

Source: https://github.com/facebookresearch/sscd-copy-detection
The upstream repository links this exact URL for sscd_disc_mixup.torchscript.pt.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import urlopen

MODEL_URL = "https://dl.fbaipublicfiles.com/sscd-copy-detection/sscd_disc_mixup.torchscript.pt"
DEFAULT_DESTINATION = Path("models/sscd_disc_mixup.torchscript.pt")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--destination", type=Path, default=DEFAULT_DESTINATION)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--expected-sha256", default="")
    parser.add_argument("--metadata-output", type=Path)
    args = parser.parse_args()

    destination: Path = args.destination
    if destination.exists() and not args.force:
        raise SystemExit(f"Already exists: {destination}. Use --force to replace it.")
    destination.parent.mkdir(parents=True, exist_ok=True)

    digest = hashlib.sha256()
    with (
        urlopen(MODEL_URL, timeout=60) as response,
        tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as temporary,
    ):
        temporary_path = Path(temporary.name)
        while chunk := response.read(1024 * 1024):
            temporary.write(chunk)
            digest.update(chunk)
    actual_sha256 = digest.hexdigest()
    expected_sha256 = args.expected_sha256.strip().lower()
    if expected_sha256 and actual_sha256 != expected_sha256:
        temporary_path.unlink(missing_ok=True)
        raise SystemExit(
            f"SSCD artifact digest mismatch: expected {expected_sha256}, got {actual_sha256}"
        )
    try:
        shutil.move(str(temporary_path), destination)
    finally:
        temporary_path.unlink(missing_ok=True)

    metadata = {
        "schema": "creatorproof.fetched_model_artifact.v1",
        "component_id": "copy-retrieval-sscd",
        "provider": "sscd-disc-mixup-torchscript",
        "source": MODEL_URL,
        "destination": str(destination.resolve()),
        "artifact_sha256": actual_sha256,
        "expected_sha256": expected_sha256 or None,
        "digest_verified": bool(expected_sha256),
        "fetched_at": datetime.now(UTC).isoformat(),
        "promotion_note": (
            "Create a new ModelBundle identity with this digest before selecting the artifact."
        ),
    }
    if args.metadata_output:
        args.metadata_output.parent.mkdir(parents=True, exist_ok=True)
        args.metadata_output.write_text(
            json.dumps(metadata, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(metadata, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
