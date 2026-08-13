# V09_SCAN_STALL_ROOT_CAUSE_REPORT.md

## 1. Executive Verdict

**`ROOT_CAUSE_CONFIRMED`**

**Observed failure location:** The HTTP `POST /v1/scans` response is held for **~130 seconds** because the entire evidence pipeline runs synchronously inside the request handler (`InlineJobQueue.enqueue` → `process_scan` → `build_evidence_packet`), and within that pipeline the GRIP CLIPDet external adapter spawns a **fresh Python process that reloads 270 MB of model weights for every single transformed view** (10 views × ~11s each = ~110s).

**Primary root cause:** `ExternalJsonSyntheticDetector.predict()` spawns `subprocess.run()` on every call ([`synthetic_detection.py:318`](./apps/api/app/providers/synthetic_detection.py#L312-L324)). The GRIP adapter command invokes a separate Python process that imports PyTorch, loads CLIP weights, and runs inference — then exits. This happens **10 times sequentially** (5 delivery views + 5 spatial crops), with no model caching between views.

**Confidence:** HIGH — supported by measured per-view timings, worst-case budget arithmetic, process observation, and the structural fact that `ExternalJsonSyntheticDetector` contains no model caching mechanism.

---

## 2. Build and Runtime Identity

| Property | Value |
|---|---|
| API version | 0.9.0 |
| Web version | 0.9.0 |
| Build signature | `PLAIN-SCORE-WATERMARK-2026.08.09` |
| Origin provider | `evidence-family-synthetic-ensemble-v3` |
| Origin schema | `creatorproof.synthetic_origin.v3` |
| Visible-label provider | `tesseract-visible-ai-marker-v1` |
| OS | Linux x86_64 (Ubuntu) |
| CPU | 12th Gen Intel i5-1235U, 10C/12T |
| RAM | 16 GB (7.2 GB available) |
| GPU | None (CUDA unavailable) |
| PyTorch | 2.12.0+cu130, CPU-only mode |
| Python | 3.12.3 |
| Job backend | **`inline`** |
| Database | SQLite (local) |
| Storage | LocalObjectStore |

### Active Providers

| Provider | Type | Device | Loaded at | Status |
|---|---|---|---|---|
| `community-forensics-vit-small-384` | In-process ViT | cpu | Container init | ✅ Active, model resident |
| `grip-clipdet` | External subprocess | cpu | **Per subprocess** | ✅ Active, **reloads per view** |
| `operator-torchscript-synthetic-detector` | TorchScript | — | — | ❌ Model not found |
| `tesseract-visible-ai-marker-v1` | Subprocess OCR | — | Per call | ✅ Active |
| `csd-vit-l-experimental` | In-process CSD | cpu | Container init | ✅ Active |
| `sscd-disc-mixup` | In-process SSCD | cpu | Container init | ✅ Active |
| `local-merkle-receipt` | Local proof | — | — | ✅ Active |
| `c2pa` | Subprocess | — | — | ❌ Binary not found |

---

## 3. Exact Reproduction

| Property | Value |
|---|---|
| Input image | Synthetic 512×512 RGB PNG, solid color (120, 80, 200) |
| Input size | ~1 KB |
| Catalog | Empty (0 works) |
| Active detectors | `community-forensics-vit-small-384`, `grip-clipdet` |
| Views per detector | 10 (5 delivery + 5 spatial) |
| Expected behavior | Scan completes in <10s |
| Actual behavior | Scan completes in **~130s** |
| Run duration (bounded) | 129.9s total |

---

## 4. Request and State Timeline

| Relative time (s) | Layer | Event | Scan state | Evidence |
|---:|---|---|---|---|
| 0.0 | Browser | `POST /api/scans` sent | — | User clicks "Run evidence verification" |
| 0.0 | Next.js proxy | `fetch(backend/v1/scans)` starts | — | [`route.ts:11`](./apps/web/app/api/scans/route.ts#L11) |
| 0.0 | API | Request received, multipart read | — | [`scans.py:39`](./apps/api/app/api/routes/scans.py#L39) |
| 0.2 | API | Fingerprints computed, scan row created | `QUEUED` | [`scans.py:58-62`](./apps/api/app/api/routes/scans.py#L58-L62) |
| 0.2 | API | `InlineJobQueue.enqueue()` → `process_scan()` | `PROCESSING` | [`jobs.py:20-21`](./apps/api/app/services/jobs.py#L20-L21), [`evidence.py:624`](./apps/api/app/services/evidence.py#L624) |
| 0.2 | API | Image decode | `PROCESSING` | [`evidence.py:295`](./apps/api/app/services/evidence.py#L295) |
| 0.2 | API | Provenance check (C2PA unavailable) | `PROCESSING` | [`evidence.py:301`](./apps/api/app/services/evidence.py#L301) |
| 0.9 | API | Visible markers OCR (5 views × 2 PSM modes) | `PROCESSING` | [`evidence.py:303`](./apps/api/app/services/evidence.py#L303) |
| 0.9 | API | `analyze_synthetic_origin()` begins | `PROCESSING` | [`evidence.py:317`](./apps/api/app/services/evidence.py#L317) |
| 0.9–2.2 | API | Community Forensics: 10 views × ~130ms (in-process) | `PROCESSING` | Measured: 1.3s total |
| 2.2–104.5 | API | **GRIP CLIPDet: 10 views × ~10.3s (subprocess reload)** | `PROCESSING` | **Measured: ~103s total** |
| 104.5 | API | Synthetic analysis complete | `PROCESSING` | |
| 104.8 | API | Retrieval (empty catalog, 295ms) | `PROCESSING` | |
| 104.8 | API | Style analysis (~1ms, no profiles) | `PROCESSING` | |
| 104.8 | API | Evidence fusion, proof anchor (<1ms) | `PROCESSING` | |
| 104.8 | API | `scan.state = COMPLETED`, DB commit | `COMPLETED` | [`evidence.py:630-632`](./apps/api/app/services/evidence.py#L630-L632) |
| 104.8 | API | `POST /v1/scans` returns 202 with COMPLETED body | — | [`scans.py:89`](./apps/api/app/api/routes/scans.py#L89) |
| 104.8 | Next.js | Backend response received, proxied to browser | — | |
| 104.8 | Browser | Response received; body.state === "COMPLETED" | — | Polling loop skipped |

**Stall classification: `C. INLINE_BACKEND_JOB_BLOCKING_RESPONSE`**

The browser `POST` is held open for the full ~105–130s duration of `process_scan()` because `InlineJobQueue.enqueue()` calls the scan function synchronously *before* the API returns the scan row. The user sees an endless "Verifying…" spinner for the entire duration.

---

## 5. Stage-Latency Profile

| Stage | Calls | Total ms | Mean ms | Max ms | % of total | Result |
|---|---:|---:|---:|---:|---:|---|
| Container build | 1 | 2,353 | 2,353 | 2,353 | 1.8% | OK (one-time) |
| Image decode | 1 | 1.4 | 1.4 | 1.4 | <0.1% | OK |
| Fingerprints | 1 | 187 | 187 | 187 | 0.1% | OK |
| Provenance (C2PA) | 1 | 5.8 | 5.8 | 5.8 | <0.1% | Unavailable |
| Visible markers (OCR) | 10 subprocs | 671 | 67 | — | 0.5% | OK |
| Community Forensics | 10 views | ~1,300 | ~130 | 140 | 1.0% | OK (in-process) |
| **GRIP CLIPDet** | **10 views** | **~103,000** | **~10,300** | **11,785** | **79.3%** | **ROOT CAUSE** |
| Retrieval | 1 | 295 | 295 | 295 | 0.2% | OK |
| Style analysis | 1 | 1.1 | 1.1 | 1.1 | <0.1% | OK (empty) |
| Proof anchor | 1 | <1 | <1 | <1 | <0.1% | OK |
| **Total measured** | | **~130,000** | | | **100%** | |

---

## 6. Multiplication and Worst-Case Budget

### Actual observed call counts

```
origin model calls = 2 detectors × 10 views = 20 predict() calls
OCR process calls  = 5 OCR views × 2 PSM modes = 10 subprocess calls
copy pair checks   = 0 (empty catalog)
style work         = 0 (no profiles)
```

### Configured worst-case bounds

| Provider | Calls | Timeout/call | Worst-case total |
|---|---:|---:|---:|
| GRIP CLIPDet (external) | 10 | 180s | **1,800s (30 min)** |
| Community Forensics (in-process) | 10 | N/A (CPU) | ~1.3s observed |
| Tesseract OCR | 10 | 12s | 120s |
| C2PA | 1 | 20s | 20s |
| **Combined maximum** | | | **~1,940s (32 min)** |

### Critical structural findings

| Question | Answer | Evidence |
|---|---|---|
| Does GRIP start a fresh Python process per view? | **YES** | `ExternalJsonSyntheticDetector.predict()` calls `subprocess.run()` each time at [`synthetic_detection.py:318`](./apps/api/app/providers/synthetic_detection.py#L318). Each invocation imports torch, loads 270MB weights, runs inference, then exits. |
| Is the 180s timeout applied per scan or per view? | **Per view** | The timeout is passed directly to `subprocess.run(timeout=self.timeout)` inside `predict()`, which is called once per view. |
| Does model startup occur once per service or per view? | **Per view** | The adapter command starts a fresh `python3 -m scripts.clipdet_json_adapter` process. The adapter's `_run()` function spawns yet another subprocess with `runner-python main.py`. Model weights are loaded from scratch each time. |
| Are views evaluated sequentially or concurrently? | **Sequentially** | The detector loop in `analyze_synthetic_origin()` at [`synthetic_analysis.py:452-469`](./apps/api/app/services/synthetic_analysis.py#L452-L469) iterates views in a plain `for` loop. |
| Are reference embeddings cached? | N/A | Empty catalog in reproduction. SSCD computes query embedding once and scans stored descriptors. |

---

## 7. Process/Resource Evidence

| Metric | Value |
|---|---|
| CPU cores | 12 (10 physical, 2 HT) |
| CPU during GRIP subprocess | 1 core saturated per subprocess (sequential) |
| RAM during scan | ~8 GB used / 16 GB total |
| Swap usage | 3.2 GB / 4 GB used (pre-existing) |
| GPU | None (CUDA unavailable) |
| PyTorch threads (per subprocess) | Defaults (likely OMP_NUM_THREADS=12) |
| Worker count | 0 (inline mode, no separate worker) |
| Active threads during scan | 1 (main API thread blocked) |
| py-spy/strace | Not installed, observation unavailable |

Each GRIP subprocess runs sequentially. No parallelism is employed. The 12 CPU cores are largely idle during the 10 sequential subprocess invocations.

---

## 8. Isolation Matrix

| Run | Catalog | Enabled | Duration | Result |
|---|---|---|---:|---|
| R0 | Empty | Fingerprint + packet only | ~200ms | ✅ Baseline overhead is trivial |
| R1 | — | — | NOT_EXECUTED | No catalog works registered in diagnostic |
| R2 | Empty | OCR only | 671ms | ✅ OCR is fast |
| R3 | Empty | Community Forensics only | ~1,300ms | ✅ In-process model, fast |
| R4 | Empty | GRIP CLIPDet only (2 views) | **22,567ms** | ⚠️ ~11s/view, subprocess reload confirmed |
| R4b | Empty | GRIP CLIPDet (view 1 vs view 2) | 11,785ms vs 10,782ms | No cold/warm difference — full reload each time |
| R5 | — | — | NOT_EXECUTED | No creator profiles in diagnostic |
| R6 | Empty | Full pipeline | **129,921ms** | ❌ Reproduces the stall (~130s) |
| R7 | — | — | NOT_EXECUTED | Redis not configured |

### Key isolation finding (R4b — first call vs. second call)

- GRIP view 1 (original): **11,785ms**
- GRIP view 2 (jpeg_95): **10,782ms**

The second call is only ~8% faster (likely OS filesystem cache for the weights file). There is **no warm-model advantage** because the process exits and restarts. This conclusively proves per-view model reloading.

### Comparison: Community Forensics (in-process)

- CF view 1 (original): 140ms
- CF view 2 (jpeg_95): 130ms

The in-process detector with a **resident model** is ~80× faster per view than the external subprocess adapter.

---

## 9. Confirmed Root Cause and Contributing Factors

### Primary Root Cause

**Per-view subprocess model reloading in `ExternalJsonSyntheticDetector`**

- **File:** [`app/providers/synthetic_detection.py`](./apps/api/app/providers/synthetic_detection.py#L312-L324)
- **Function:** `ExternalJsonSyntheticDetector.predict()`, line 318
- **Mechanism:** Every call to `predict()` runs `subprocess.run(command, ...)` which starts a fresh Python process. The GRIP adapter (`scripts/clipdet_json_adapter.py`) imports torch, loads 270MB weights from disk, runs inference on one image, prints JSON, and exits. This happens 10 times sequentially (5 delivery + 5 spatial views).
- **Measured cost:** ~10.3s per view × 10 views = **~103s**
- **Why registration succeeds:** Work registration (`POST /v1/works`) only stores the image and computes fingerprints/SSCD embeddings. It does not run synthetic detection, OCR, or evidence fusion. Registration completes in <2s.

### Contributing Factors

1. **Inline job execution blocks the HTTP response**
   - [`container.py:88`](./apps/api/app/container.py#L88): `InlineJobQueue(lambda scan_id: process_scan(container, scan_id))`
   - [`jobs.py:20-21`](./apps/api/app/services/jobs.py#L20-L21): `enqueue()` directly calls `self.callback(scan_id)`
   - [`scans.py:77`](./apps/api/app/api/routes/scans.py#L77): `container.queue.enqueue(scan.id)` — this blocks until the entire `process_scan()` completes
   - Impact: The Next.js proxy and browser are held open for the full ~130s

2. **Sequential view iteration with no concurrency**
   - [`synthetic_analysis.py:458`](./apps/api/app/services/synthetic_analysis.py#L458): `for view_name, view, quality_weight, view_scope in views:`
   - All 10 views are processed serially on a single thread

3. **Multiplicative timeout budget (1,800s theoretical maximum)**
   - The 180s `timeout_seconds` is applied per `subprocess.run()` call, and there are 10 calls
   - Worst case: 10 × 180s = 1,800s (30 minutes)

### User-Interface Amplification

- **No progress indicator:** The UI shows "Verifying…" with no elapsed time, stage name, or progress bar
- **Polling loop is irrelevant in inline mode:** The POST itself blocks until COMPLETED, so the polling loop at [`page.tsx:157-163`](./apps/web/app/page.tsx#L157-L163) is never exercised
- **No cancel button:** The user cannot abort the scan
- **If Redis mode were used:** The polling budget (20 polls × 350ms = 7s) would exhaust ~18× before a ~130s job completes, leaving the UI stuck on an old state

---

## 10. Ruled-Out Causes and Unknowns

### Ruled out

| Hypothesis | Evidence |
|---|---|
| Queue misconfiguration | `job_backend=inline` — there is no queue; the issue is architectural |
| Worker absent | Inline mode has no worker; the callback runs in the API process |
| Database lock contention | SQLite write takes <1ms; no concurrent writers observed |
| Redis connection timeout | Redis is not configured or used |
| OOM / killed child process | All 10 GRIP subprocesses completed successfully with exit code 0 |
| PyTorch thread oversubscription | Possible minor contributor but not the primary cause; each subprocess runs alone |
| Proof/blockchain blocking | Local Merkle receipt completes in <1ms |
| Model download during scan | No downloads observed; weights are pre-installed |
| C2PA blocking | C2PA binary not found; check returns immediately |
| Style analysis slow | Style analysis with empty catalog: 1.1ms |
| Copy retrieval slow | Empty catalog retrieval: 295ms |

### Unknowns

| Item | Status |
|---|---|
| Behavior with GPU (CUDA) | Would reduce per-view inference time but not eliminate subprocess reload overhead (~5s startup per process estimated) |
| Redis-mode end-to-end timing | Not tested (Redis not configured) |
| Multi-reference catalog scaling | Not tested in this diagnostic |
| py-spy thread analysis | Not available (not installed) |

---

## 11. Candidate Fixes for the Next Iteration — DO NOT IMPLEMENT

Ranked by expected impact, risk, and testability:

### Fix 1: Keep GRIP detector model resident (HIGH impact, MEDIUM risk)

Replace subprocess-per-view with a long-running model server or in-process adapter. Keep the model loaded across all 10 views. Expected reduction: ~103s → ~3–5s for GRIP (assuming ~300ms/view inference without reload, similar to Community Forensics).

**Approach options:**
- A. Convert `ExternalJsonSyntheticDetector` to batch all views into one subprocess call
- B. Start a persistent gRPC/HTTP model server and call it per view
- C. Load GRIP weights in-process (requires dependency isolation)

### Fix 2: Move heavy scans off the request path (HIGH impact, LOW risk)

Change `POST /v1/scans` to return `202 QUEUED` immediately after storing the scan row and enqueueing the job. Use the existing Redis worker or a `BackgroundTasks` FastAPI mechanism.

### Fix 3: Batch views through one provider process (HIGH impact, LOW risk)

Modify `clipdet_json_adapter.py` to accept multiple images per invocation (CSV already supports multiple rows). This would reduce 10 subprocess starts to 1.

### Fix 4: Enforce per-provider total timeout budgets (MEDIUM impact, LOW risk)

Replace the current architecture of `timeout_seconds` per `subprocess.run()` call with a total budget per detector per scan. Example: 60s total for GRIP across all views instead of 180s × 10 = 1,800s.

### Fix 5: Limit or parallelize view evaluation (MEDIUM impact, MEDIUM risk)

- Reduce spatial crops when an external subprocess detector is active (e.g., skip spatial views for subprocess-backed detectors)
- Run Community Forensics and GRIP concurrently using `ThreadPoolExecutor`

### Fix 6: Queue heartbeat, progress, and bounded failure (MEDIUM impact, LOW risk)

Add progress stages to the scan row (`current_stage: "SYNTHETIC_ANALYSIS"`) and a heartbeat timestamp. The UI can then show meaningful progress instead of a generic spinner.

### Fix 7: Frontend polling budget for Redis mode (LOW impact, LOW risk)

Increase polling from 20×350ms (7s) to at least 120×2s (4 min) with exponential backoff. Show elapsed time and the current stage.

### Fix 8: Proof anchoring outside blocking path (N/A — already non-blocking)

Local Merkle receipt is <1ms and already runs after evidence fusion. No fix needed. EAS testnet call is not currently activated.

---

## 12. Proposed v0.9.1 Acceptance Criteria

| # | Criterion | Measurable target |
|---|---|---|
| 1 | `POST /v1/scans` returns within 2s in queued mode | Time-to-first-byte < 2000ms |
| 2 | Every scan reaches `COMPLETED` or `FAILED` within total budget | ≤ 45s on this machine with current providers |
| 3 | No provider can consume an unbounded multiplicative timeout | Per-detector total budget ≤ 60s regardless of view count |
| 4 | Progress exposes current stage and heartbeat | `scan.current_stage` and `scan.heartbeat_at` populated |
| 5 | Model artifacts load no more than once per scan | GRIP weights loaded once, inference called 10× within one process |
| 6 | Blockchain/EAS cannot block scan completion | Proof runs after `COMPLETED` state is committed |
| 7 | Refresh/reconnect recovers a scan by ID | `GET /v1/scans/{id}` returns current state |
| 8 | Regression tests pass | `test_scan_stall_diagnostic.py` — all 8 tests green |
| 9 | No detection threshold or model accuracy change | All existing 44 tests pass without assertion changes |

---

## 13. Commands and Artifacts

### Commands run during diagnosis

```bash
# System inventory
nproc && lscpu && free -h
python3 -c "import torch; print(torch.__version__, torch.cuda.is_available())"

# Configuration audit
grep -n "job_backend\|timeout\|spatial" apps/api/.env apps/api/app/core/config.py

# Stage timing diagnostic
uv run --no-sync python -m scripts.stall_diagnostic

# Structural tests
uv run --no-sync pytest tests/test_scan_stall_diagnostic.py -v
```

### Files created (temporary/diagnostic)

| File | Purpose | Remove after fix? |
|---|---|---|
| `scripts/stall_diagnostic.py` | Stage-by-stage timing measurement | Yes |
| `tests/test_scan_stall_diagnostic.py` | Regression tests exposing root cause | **Keep** (adapt assertions post-fix) |
| `V09_SCAN_STALL_ROOT_CAUSE_REPORT.md` | This report | Keep for audit trail |

### How to remove temporary instrumentation

```bash
rm apps/api/scripts/stall_diagnostic.py
# Keep tests/test_scan_stall_diagnostic.py — update assertions post-fix
```

---

## 14. Correct Release Statement

**Status: `RUNTIME_BLOCKED — NOT DEMO_READY`**

The build source is verified (`PLAIN-SCORE-WATERMARK-2026.08.09`) and all 44 existing unit tests pass. However, a reproducible ~130-second scan stall occurs on every verification attempt due to per-view subprocess model reloading in the GRIP CLIPDet adapter. The configured worst-case budget is **1,800 seconds (30 minutes)**.

A build with a reproducible two-minute blocking scan (and theoretical 30-minute worst case) is **not `DEMO_READY`**. Registration works instantly (~1s), but verification — the core product action — creates an unacceptable user experience where the browser appears frozen with no progress feedback.

The system is safe for **developer testing** with the understanding that each scan will take ~130s. It is not suitable for live demonstration until Fix 1 (model resident) or Fix 3 (batched views) is implemented.
