"""Run the backend Phase 1 preflight from the repository root using its uv environment."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path


def main() -> int:
    uv_binary = shutil.which("uv")
    if uv_binary is None:
        print(
            json.dumps(
                {
                    "schema": "creatorproof.phase1_preflight.v1",
                    "valid": False,
                    "failures": ["UV_NOT_INSTALLED"],
                }
            )
        )
        return 2
    api_root = Path(__file__).resolve().parents[1] / "apps" / "api"
    return subprocess.run(
        [uv_binary, "run", "--no-sync", "python", "-m", "scripts.phase1_preflight", *sys.argv[1:]],
        cwd=api_root,
        check=False,
    ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
