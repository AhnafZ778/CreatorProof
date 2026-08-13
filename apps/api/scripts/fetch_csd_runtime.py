from __future__ import annotations

import argparse
import hashlib
import subprocess
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
    args = parser.parse_args()

    if not (args.repo_path / ".git").is_dir():
        args.repo_path.parent.mkdir(parents=True, exist_ok=True)
        _run("git", "clone", "--depth", "1", CSD_REPO, str(args.repo_path))
    commit = _run("git", "rev-parse", "HEAD", cwd=args.repo_path)

    try:
        from huggingface_hub import hf_hub_download
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
    print(f"CSD repository commit: {commit}")
    print(f"CSD checkpoint: {downloaded}")
    checkpoint_sha256 = _sha256(downloaded)
    print(f"CSD checkpoint SHA-256: {checkpoint_sha256}")
    print("If PyTorch rejects the legacy checkpoint, explicitly set:")
    print("  CREATORPROOF_STYLE_ALLOW_LEGACY_PICKLE=true")
    print(f"  CREATORPROOF_STYLE_CSD_EXPECTED_SHA256={checkpoint_sha256}")
    print(
        "WARNING: upstream CSD currently flags a model-weight discrepancy. "
        "Run check_style_ai and benchmark_style_retrieval before claiming learned style accuracy."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
