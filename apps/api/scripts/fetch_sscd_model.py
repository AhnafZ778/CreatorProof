"""Fetch the official SSCD DISC mixup TorchScript inference artifact.

Source: https://github.com/facebookresearch/sscd-copy-detection
The upstream repository links this exact URL for sscd_disc_mixup.torchscript.pt.
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import tempfile
from pathlib import Path
from urllib.request import urlopen

MODEL_URL = "https://dl.fbaipublicfiles.com/sscd-copy-detection/sscd_disc_mixup.torchscript.pt"
DEFAULT_DESTINATION = Path("models/sscd_disc_mixup.torchscript.pt")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--destination", type=Path, default=DEFAULT_DESTINATION)
    parser.add_argument("--force", action="store_true")
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
    try:
        shutil.move(str(temporary_path), destination)
    finally:
        temporary_path.unlink(missing_ok=True)

    print(f"Saved: {destination}")
    print(f"SHA-256: {digest.hexdigest()}")
    print("Record this digest with your build notes for reproducibility.")


if __name__ == "__main__":
    main()
