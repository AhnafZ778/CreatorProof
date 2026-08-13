# UI state matrix, accessibility checklist, and demo script

Sprint S15 deliverables. Every claim in the interface maps to an API field, and
every field listed here is one a test asserts on.

## 1. UI state matrix

### Application level

| State | Trigger | What the user sees | Rule |
| --- | --- | --- | --- |
| Checking | Health request in flight | `API CHECKING` in the status bar | Never render a result while unknown |
| Online | `/healthz` 200 | API version in the status bar | — |
| Offline | Health fails or non-200 | Red banner: nothing is simulated while the API is down | No cached or fake result may appear |
| Version mismatch | Console version ≠ API version | Red banner naming both versions | Results are not trustworthy across versions |
| Degraded | `degraded_capabilities` non-empty | Amber banner listing each capability | Never hidden behind a disclosure |

### Scan lifecycle

| State | Source | Display | Rule |
| --- | --- | --- | --- |
| Uploading | Client | Progress panel at 0% | — |
| Queued | `state=QUEUED` | Stage ledger with all stages pending | Not drawn as if running |
| Running | `state=PROCESSING` | Per-stage bars from the durable ledger | Percentages come from the server, never animation |
| Lease expired | Stage `ABANDONED` | "Lease expired, will be retried" | Honest, not hidden as still running |
| Retrying | `attempt > 1` | "attempt 2 of 3" | Retries are visible |
| Timed out (client) | 3-minute poll budget | "Live updates paused. Your scan was not cancelled." | Never implies the scan failed |
| Cancelled | `state=CANCELLED` | Explicit notice, no packet | Never shown as a clean pass |
| Failed | `state=FAILED` | Error code surfaced | No partial evidence presented as complete |
| Completed | `state=COMPLETED` | Coverage, then decision, then lanes, then proof | Order is fixed |

### Coverage, shown before any decision

| `coverage_status` | Tone | Headline |
| --- | --- | --- |
| `COMPLETE` | Green | Every eligible work in this catalog was searched |
| `EMPTY_SCOPE` | Amber | Nothing was searched |
| `PARTIAL` | Amber | Only part of the catalog was searched |
| `DEGRADED` | Amber | The search ran in a reduced mode |
| `TRUNCATED` | Amber | The candidate list hit its limit |
| `FAILED` | Red | The search did not complete |
| absent | Amber | Coverage was not reported; treat as unverified |

`EMPTY_SCOPE` with a `PASS_BY_POLICY` is the single most dangerous combination in
the product. It is rendered as a warning above the decision, never below it, and
never inside a collapsed section.

### Lanes, answered separately

| Lane | Hit | Clear | Not checked |
| --- | --- | --- | --- |
| Copy | Strongest matching stored work named | No match above threshold, qualified by coverage | Retrieval unavailable |
| AI origin | Signals consistent with AI generation | No signal above threshold | Disabled by policy, or detector unavailable |
| Creator profile | Resembles a registered profile (advisory) | No resemblance above threshold | No profile registered |
| Rights | Recorded rights path and intended use | `EXISTING_LICENSE` | No rights recorded |

A lane that was not checked uses a dashed border and a `?` glyph. It is never
styled like a pass.

### Proof panel

| `commitment_scope` | Heading | Fields |
| --- | --- | --- |
| `PUBLIC_EVM_ATTESTATION` | Anchored on a public chain | Network, chain ID, transaction, block, attestation UID, schema UID, attester, packet hash, confirmations, explorer link |
| Local | Anchored in the append-only log | Log ID, leaf index, tree size, Merkle root, packet hash, inclusion verified |

The local panel states in prose that it is not a blockchain. `anchor_status` of
`PENDING` or `FAILED` is displayed as-is; a failed anchor never renders as
anchored.

## 2. Accessibility checklist

| Requirement | How it is met |
| --- | --- |
| Keyboard navigation | Every control is a native `button`, `a`, `input`, `select` or `details`; no click-only `div`s |
| Skip link | "Skip to the workbench" is the first focusable element |
| Visible focus | 3px outline with 3px offset on every interactive element |
| Status not by colour alone | Glyphs (`!`, `✓`, `~`, `?`), text labels, and dashed borders accompany every colour |
| Live regions | Progress and verification results use `role="status"` with `aria-live="polite"` |
| Errors announced | Failures use `role="alert"` |
| Toggle state | Judge/technical buttons expose `aria-pressed` |
| Landmarks | `nav`, `main`, `header`, `footer`, and labelled `section`s |
| Decorative elements hidden | Progress bars and marker dots are `aria-hidden` with the value in adjacent text |
| Contrast | Body text `#f4f7fb` and muted `#b3bed0` on `#080d19` exceed 4.5:1; status colours are paired with text |
| Reduced motion | The only animation is a 1.4s pulse on the running stage marker |
| Zoom and reflow | Layout reflows at 1080px and 520px without horizontal scrolling |

### Layout targets

| Target | Notes |
| --- | --- |
| Laptop 1440×900 | Primary demo layout |
| Projector 1920×1080 | Headline and decision readable from the back of a room |
| Mobile 390×844 | Single column; scenario cards stack |
| Screen recording 1280×720 | Coverage and decision fit above the fold |

## 3. Judge-mode demo script (10 minutes)

Preparation: API and web running, `GET /readyz` clean, browser at 100% zoom, judge
mode selected.

**0:00 — The problem (45s).** "Before publishing, three separate questions matter:
was AI involved, does this reuse someone's registered work, and does it resemble a
known creator. Most tools blur them into one score. We keep them apart, and we
prove our answer was not edited afterwards."

**0:45 — Run a scenario (60s).** Demo mode, "Exact reuse of a registered work".
Say plainly: the sample images are generated in the browser and registered through
the same API as any customer's work. Nothing is mocked.

**1:45 — The stage ledger (45s).** Point at the live stages. "This is the durable
ledger on the server, not an animation. If the worker dies, the lease expires,
another worker picks it up, and this timeline shows that honestly."

**2:30 — Coverage first (60s).** "Before the decision: coverage. Every eligible
work was searched. If it had not been, this banner would say so, above the
decision. A clean result over an empty catalog means nothing, and we refuse to
present it as a pass."

**3:30 — The decision and the lanes (90s).** Read the bottom line, then the four
lanes. Emphasise: this is a policy decision under the customer's own rules and
review evidence. It is not a legal infringement finding.

**5:00 — Proof (90s).** Open the proof panel. If anchored: chain, transaction,
block, UID, schema, packet hash, and the explorer link — open it. If local: say
directly that this is an append-only transparency receipt, not a blockchain.

**6:30 — Independent verification (90s).** Click "Verify in this browser". Walk
through the checks: the canonical form reproduces the digest, the Ed25519
signature verifies against the published key, the transparency leaf reproduces the
root. "This ran in your browser against the downloaded package. You are not
trusting our server's opinion of its own evidence."

**8:00 — Why a chain (60s).** "A database proves this to us. A chain proves it to
a creator, a brand, and a court-appointed expert who all distrust us. That is the
multi-party problem. The chain proves existence and time — not that the claim is
true. We are careful about that distinction."

**9:00 — Close (60s).** Offline verifier, deletion receipts, tenant isolation,
signed webhooks. Invite questions.

### Rehearsal matrix

| Condition | Expected behaviour |
| --- | --- |
| Three consecutive full runs | Identical outcomes; no restarts |
| Network unavailable | Offline banner; no fabricated results |
| Optional model unavailable | Degraded banner; coverage reports `DEGRADED` |
| EAS delayed | Anchor `PENDING`; evidence and local receipt unaffected |
| EAS failed | Anchor `FAILED`, stated plainly; never shown as anchored |
| Worker killed mid-scan | Lease reaped, stage retried, scan completes |

### Questions to have answers ready for

- Why blockchain instead of a database? Section 1 of the governance document.
- What is actually on chain? One 32-byte hash. Nothing else, ever.
- How does this survive GDPR erasure? Content is off chain and deletable; the hash
  commits to data that can no longer be reconstructed.
- What if your signing key leaks? The compromise runbook, including notification.
- Can you prove infringement? No. Nobody can from a scan, and we say so in the
  product, the API, and every export.
