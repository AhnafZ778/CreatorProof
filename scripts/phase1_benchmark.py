"""Repository-root entry point for the isolated Phase 1 benchmark."""

import runpy
import sys
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1] / "apps" / "api"
sys.path.insert(0, str(API_ROOT))

if __name__ == "__main__":
    runpy.run_path(str(API_ROOT / "scripts" / "phase1_benchmark.py"), run_name="__main__")
