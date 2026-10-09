"""Compare frontend bytes against the frozen pre-existing worktree baseline."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "docs/phase1-frontend-baseline.json"


def snapshot(root: Path = ROOT) -> dict[str, str]:
    paths = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", "apps/web"],
        cwd=root, capture_output=True, check=True,
    ).stdout.decode().split("\0")
    return {name: hashlib.sha256((root / name).read_bytes()).hexdigest()
            for name in sorted(set(paths)) if name and (root / name).is_file()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record", action="store_true",
                        help="Record baseline once; refuses to overwrite an existing baseline")
    args = parser.parse_args()
    current = snapshot()
    if args.record:
        with BASELINE.open("x") as output:
            json.dump({"schema": "creatorproof.frontend-baseline.v1", "files": current},
                      output, indent=2, sort_keys=True)
            output.write("\n")
    baseline = json.loads(BASELINE.read_text())["files"]
    changes = [name for name in sorted(current.keys() | baseline.keys())
               if current.get(name) != baseline.get(name)]
    print(json.dumps({"frontend_unchanged": not changes, "changed_files": changes,
                      "file_count": len(current), "baseline": str(BASELINE.relative_to(ROOT))},
                     indent=2))
    return 1 if changes else 0


if __name__ == "__main__":
    raise SystemExit(main())
