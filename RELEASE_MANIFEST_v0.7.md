# CreatorProof v0.7 release manifest

Build: `0.7.0 / TRI-LANE-PROVENANCE-2026.08.09`

## Start here

1. `README.md` — product and quick start.
2. `MASTER_EXECUTION_PROMPT_v0.7.md` — complete agentic installation and validation prompt.
3. `V07_EXECUTION_REPORT.md` — checks actually run in the packaging workspace.
4. `docs/V07_RESEARCH_ARCHITECTURE.md` — architecture, business model, research basis.
5. `docs/V07_DETECTION_MATH.md` — active equations and decision gates.
6. `docs/V07_VALIDATION_PROTOCOL.md` — empirical validation/red-team protocol.
7. `docs/V07_REPOSITORY_PLAYBOOK.md` — repositories, datasets, boundaries, exact prompts.

## New v0.7 runtime files

- `apps/api/app/providers/synthetic_detection.py`
- `apps/api/app/services/synthetic_analysis.py`
- `apps/api/app/providers/provenance.py`
- `apps/api/app/providers/proof.py`
- `apps/api/scripts/fetch_community_forensics_model.py`
- `apps/api/scripts/check_synthetic_ai.py`
- `apps/api/scripts/calibrate_synthetic_scores.py`
- `apps/api/scripts/benchmark_synthetic_detection.py`
- `apps/api/scripts/verify_proof_receipt.py`
- `apps/api/requirements-synthetic.txt`
- `apps/api/requirements-blockchain.txt`

## Test/build status at packaging

- Ruff lint: pass.
- Ruff format check: pass.
- Pytest: 27 passed.
- TypeScript: pass.
- Next.js production build: pass.
- Learned model artifacts: not bundled; activation scripts included.
- C2PA binary: not bundled; official tool required.
- EAS credentials: not bundled; optional testnet configuration documented.

## Archive exclusions

The release archive intentionally excludes:

- `.env` and `.env.local` files;
- API/private keys and credentials;
- uploaded/reference/candidate artwork;
- model weights and external repositories;
- `.venv`, `node_modules`, `.next`, caches, databases, and runtime data;
- screenshots and temporary validation assets.

These exclusions keep the archive small, lawful, and safe to share. The execution prompt reconstructs
the optional local runtimes and reports exactly what activated.
