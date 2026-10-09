"""Disposable API for frontend contract checks; never uses project .env or live providers.

Run from apps/api with its Python environment. Set FRONTEND_FIXTURE_DIR to an
empty temporary directory. This script is test infrastructure, not an app entrypoint.
"""
from pathlib import Path
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "api"))

from app.core.config import Settings
from app.main import create_app
from app.services.aiand import AiAndClient, AiAndError, InvestigationResult, provider_context_hash
from app.services.model_bundle import canonical_json_digest
from PIL import Image, ImageDraw
import uvicorn

root = Path(os.environ["FRONTEND_FIXTURE_DIR"])
root.mkdir(parents=True, exist_ok=True)
image = Image.new("RGB", (320, 240), (245, 246, 248))
draw = ImageDraw.Draw(image)
draw.rectangle((30, 30, 145, 155), fill=(20, 105, 220), outline=(4, 20, 40), width=5)
draw.ellipse((165, 55, 275, 165), fill=(250, 160, 40), outline=(70, 30, 5), width=4)
draw.line((20, 205, 300, 185), fill=(25, 30, 40), width=7)
image.save(root / "artwork.png")

settings = Settings(
    _env_file=None, environment="test",
    database_url=f"sqlite:///{root / 'fixture.db'}", storage_root=root / "objects",
    job_backend="inline", dev_api_key="frontend-integration-fixture-key",
    proof_log_path=root / "proof-log.jsonl", proof_anchor_mode="none",
    sscd_model_path=root / "missing-sscd.pt", style_provider="diagnostic",
    synthetic_detector="off", synthetic_policy_mode="INFORMATIONAL",
    c2pa_mode="off", visible_ai_marker_mode="off", copy_retrieval_requirement="BASELINE_ALLOWED",
    sightengine_api_user="", sightengine_api_secret="", unsplash_access_key="",
    pixabay_api_key="", aiand_api_key="",
)

async def investigate(_client, packet):
    if (root / "fail-assistant").exists():
        raise AiAndError("Controlled fixture provider is unavailable")
    payload = {
        "summary": "Browser test fixture: inspect the recorded visual match and artist preferences before acting.",
        "evidence_references": [],
        "missing_facts": ["Verify claimant authority and the candidate's actual publication context."],
        "next_steps": ["Review the side-by-side comparison and recorded license."],
        "duplicate_groups": [], "factual_notice_draft": None,
        "unsupported_claims": ["Country of residence and legal infringement are not established by this scan."],
    }
    return InvestigationResult(payload=payload, input_hash=provider_context_hash(packet),
                               output_hash=canonical_json_digest(payload),
                               provider="browser-test-fixture", model="controlled-contract-output")

AiAndClient.investigate = investigate
app = create_app(settings)
if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("FRONTEND_FIXTURE_PORT", "8011")), access_log=False)
