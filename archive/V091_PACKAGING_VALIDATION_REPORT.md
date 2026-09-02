# CreatorProof v0.9.1 — packaging validation report

Date: 2026-08-09  
Build signature: `BATCHED-NONBLOCKING-SCAN-2026.08.09`  
Promotion in this workspace: **SOURCE_VERIFIED / TARGET-MACHINE MODEL LATENCY REQUIRED**

## Environment

| Component | Version |
|---|---:|
| Python | 3.12.13 |
| uv | 0.11.33 |
| Node.js | 24.14.0 |
| npm | 11.9.0 |
| Git | 2.51.1 |
| CreatorProof API/Web | 0.9.1 |

## Completed gates

Backend:

- Ruff lint: pass.
- Ruff format check: pass, 73 files checked.
- Pytest: **52/52 pass**.
- Non-failing dependency warning: Starlette's TestClient compatibility import is deprecated by the
  installed dependency; this did not affect the tests.

Frontend:

- TypeScript: pass, zero errors.
- Next.js 16.3.0 production build: pass.
- All expected static and dynamic routes generated.
- Non-failing host warning: npm's legacy `http-proxy` environment setting will change in a future npm major version.

## Runtime-specific evidence

The new tests establish these source/runtime contracts:

1. ten external views produce ten mapped results from one subprocess invocation;
2. the official adapter writes all manifest images into one upstream CSV invocation;
3. legacy one-image adapters share a decreasing whole-detector deadline;
4. local enqueue returns before the callback finishes;
5. `POST /v1/scans` returns `202` while a controlled background callback is still blocked;
6. progress is persisted and readable while a controlled stage is blocked;
7. legacy development `inline` configuration migrates to `local-thread`;
8. a proof-provider exception leaves the core scan `COMPLETED` and records proof `FAILED`.

## What was not claimed

The packaging workspace does not contain the user's GRIP repository, GRIP weights, SSCD weights,
Community Forensics weights, CSD weights, calibration corpus, or blockchain credentials. Therefore:

- no real GRIP wall-clock reduction is reported here;
- no AI-origin accuracy result is reported;
- no live EAS transaction is claimed;
- no production SLA is claimed;
- no browser screenshot is counted as target-machine UX verification.

Use `MASTER_EXECUTION_PROMPT_v0.9.1.md` and `scripts/benchmark_scan_latency.py` on the target machine.
Only that run can promote this package to `RUNTIME_READY` or `DEMO_READY`.

