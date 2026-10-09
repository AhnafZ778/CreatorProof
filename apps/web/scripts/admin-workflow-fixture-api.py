"""Isolated API for the complete User-to-Admin review workflow, with no live AI."""

import os
import runpy
from pathlib import Path

import uvicorn

fixture = runpy.run_path(str(Path(__file__).with_name("phase1-fixture-api.py")))
app = fixture["app"]
app.state.container.settings.candidate_retention_seconds = 604800

if __name__ == "__main__":
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=int(os.environ.get("FRONTEND_FIXTURE_PORT", "8011")),
        access_log=False,
    )
