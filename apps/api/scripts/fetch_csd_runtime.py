from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

CSD_REPO = "https://github.com/learn2phoenix/CSD.git"
HF_REPO = "tomg-group-umd/CSD-ViT-L"
HF_FILENAME = "pytorch_model.bin"


def _run(*args: str, cwd: Path | None = None) -> str:
    result = subprocess.run(
        list(args),
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fetch the external experimental CSD style runtime and record exact revisions."
    )
    parser.add_argument("--repo-path", type=Path, default=Path("vendor/CSD"))
    parser.add_argument("--model-dir", type=Path, default=Path("models/csd-vit-l"))
    parser.add_argument("--hf-revision", default="main")
    parser.add_argument("--expected-sha256", default="")
    parser.add_argument("--metadata-output", type=Path)
    args = parser.parse_args()

    if not (args.repo_path / ".git").is_dir():
        args.repo_path.parent.mkdir(parents=True, exist_ok=True)
        _run("git", "clone", "--depth", "1", CSD_REPO, str(args.repo_path))
    commit = _run("git", "rev-parse", "HEAD", cwd=args.repo_path)

    try:
        from huggingface_hub import HfApi, hf_hub_download
    except ImportError as exc:
        raise SystemExit(
            "Install requirements-style-experimental.txt before fetching the CSD checkpoint."
        ) from exc

    args.model_dir.mkdir(parents=True, exist_ok=True)
    downloaded = Path(
        hf_hub_download(
            repo_id=HF_REPO,
            filename=HF_FILENAME,
            revision=args.hf_revision,
            local_dir=args.model_dir,
        )
    )
    checkpoint_sha256 = _sha256(downloaded)
    expected_sha256 = args.expected_sha256.strip().lower()
    if expected_sha256 and checkpoint_sha256 != expected_sha256:
        raise SystemExit(
            f"CSD checkpoint digest mismatch: expected {expected_sha256}, got {checkpoint_sha256}"
        )
    resolved_hf_revision = HfApi().model_info(HF_REPO, revision=args.hf_revision).sha
    metadata = {
        "schema": "creatorproof.fetched_model_artifact.v1",
        "component_id": "style-csd",
        "provider": "csd-vit-l-experimental",
        "source_repository": CSD_REPO,
        "source_commit": commit,
        "checkpoint_repository": HF_REPO,
        "checkpoint_requested_revision": args.hf_revision,
        "checkpoint_resolved_revision": resolved_hf_revision,
        "checkpoint": str(downloaded.resolve()),
        "artifact_sha256": checkpoint_sha256,
        "expected_sha256": expected_sha256 or None,
        "digest_verified": bool(expected_sha256),
        "fetched_at": datetime.now(UTC).isoformat(),
        "unsafe_legacy_pickle_opt_in_required": True,
        "promotion_warning": (
            "Upstream reports a model-weight discrepancy; benchmark this exact checkpoint "
            "before any learned-style accuracy claim."
        ),
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
