# Pilot plan, onboarding, support, and commercial boundary

Sprint S17. This document is what a pilot customer is actually promised. Every
promise here is one the platform can keep today, not one the roadmap implies.

## 1. Commercial boundary statement

Read this first. It governs every other section.

**CreatorProof produces evidence and policy decisions. It does not determine
infringement.**

| We do | We do not |
| --- | --- |
| Search a declared catalog and report what matched | Assert that a match is infringement |
| Report signals consistent with AI generation | Certify that an image is or is not AI-generated |
| Report resemblance to a registered creator profile | Establish authorship or ownership |
| Apply the customer's own policy and return a decision | Give legal advice |
| Prove an evidence packet existed at a time, unaltered | Prove the contents of that packet are true |
| Report coverage honestly, including when it is incomplete | Present an unsearched catalog as a clean result |

Three consequences, stated plainly because they are the ones that get misread:

- **A `PASS_BY_POLICY` is not a clearance.** It means the configured policy did not
  raise an objection over the scope that was actually searched.
- **An anchored proof is not a true claim.** The chain proves a specific packet
  existed at a specific time and has not been edited. It says nothing about
  whether the analysis inside it was correct.
- **A creator-profile hit is advisory only.** Style resemblance is not protectable
  on its own in most jurisdictions, and the product never escalates on it alone.

Customer-facing material may not describe outputs as "verified original",
"cleared", "copyright checked", or "AI-free". Those phrases claim certainty the
system does not have, and the evidence packet contradicts them in writing.

## 2. Pilot plan

A pilot runs four weeks and is judged on measured behaviour, not enthusiasm.

| Phase | Duration | Goal | Exit condition |
| --- | --- | --- | --- |
| 0. Fit | 3 days | Confirm the customer has a pre-publication decision to make | A named reviewer and a real workflow exist |
| 1. Onboarding | 3 days | Tenant, credentials, catalog imported | Catalog imported with a reconciled count |
| 2. Shadow | 2 weeks | Run alongside the existing process, change nothing | Decisions compared, disagreements reviewed |
| 3. Review | 3 days | Measure against the metrics below | Both sides agree on what happened |
| 4. Decision | 2 days | Continue, adjust, or stop | Written outcome either way |

Shadow mode is not optional. A detection system that has never been measured
against a customer's real content should not be making their publication
decisions, and a pilot that skips this step produces an opinion rather than a
result.

### What is measured

| Metric | Source | Target for a first pilot |
| --- | --- | --- |
| Onboarding time | Tenant creation to first successful scan | Under one working day |
| Coverage completeness | `coverage_status` on every scan | `COMPLETE` on 95%+ of scans |
| Reviewer time per case | Review case open to resolution | Established as a baseline, then reduced |
| Repeat use | Scans in week 4 versus week 1 | Flat or rising |
| Verification success | Independent verifications that pass | 100%, no exceptions |
| False pass from incomplete scope | Manual audit of every non-`COMPLETE` scan | Zero |
| Rollback completion time | Drill, measured | Under 30 minutes |

The last two are pass/fail. A single false pass caused by incomplete scope ends
the pilot and triggers a fix, because that failure mode is the one that destroys
trust in everything else the product says.

## 3. Onboarding guide

### Step 1 — Create the tenant and credentials

Issue one credential per integration, never one shared key. Scope each to the
minimum it needs.

| Integration | Role | Scopes |
| --- | --- | --- |
| Catalog import job | `CATALOG_MANAGER` | `works:write`, `works:read` |
| Publishing pipeline | `SERVICE_ACCOUNT` | `scans:write`, `scans:read` |
| Reviewer console | `REVIEWER` | `review:read`, `review:write`, `scans:read` |
| Auditor | `AUDITOR` | read scopes only |

The secret is returned exactly once at creation. There is no recovery path; a lost
secret is revoked and reissued, which is the correct behaviour for a credential
that authorises evidence generation.

### Step 2 — Import the catalog

Use `POST /v1/works/bulk`, up to `bulk_import_max_files` per request. It returns
`207` with per-file outcomes, so a malformed file never silently disappears.

```bash
curl -X POST http://localhost:8000/v1/works/bulk \
  -H "X-API-Key: $CREATORPROOF_API_KEY" \
  -F "catalog_id=brand-library" \
  -F "files=@hero.png" -F "files=@logo.png" \
  -F 'manifest=[{"filename":"hero.png","title":"Hero","rights_path":"EXISTING_LICENSE"}]'
```

**Reconcile the count before going further.** Compare `imported` against the source
system. An import that quietly dropped files produces exactly the failure this
product exists to prevent: a clean scan over a catalog that was missing the work
that would have matched.

### Step 3 — Record rights

A work without recorded rights can still be scanned, but the rights lane reports
"no rights recorded" and the policy engine cannot clear it on a licence basis.
Register the party, the claim, and any licence before shadow mode begins.

### Step 4 — Configure policy

Start from the default policy version and adjust in dry-run.
`POST /v1/policies/dry-run` re-evaluates one completed scan's recorded evidence
under other policy versions and returns what each would have decided. Run it
across a handful of representative scans — especially ones that were reviewed or
blocked — before activating a new version, so a threshold change is understood
before it affects a real decision.

Policy versions are immutable. A change creates a new version, and every decision
trace records which version applied, so a past decision can always be explained
under the rules in force at the time rather than today's.

### Step 5 — Verify independently, once, together

Before shadow mode, have the customer run the offline verifier themselves on a
real statement:

```bash
python scripts/verify_evidence_statement.py verification-package.json \
  --expected-issuer-key-sha256 "$CREATORPROOF_ISSUER_KEY_PIN"
```

The fingerprint must come from the published deployment manifest or another
independent channel, never from the downloaded package itself. This takes ten
minutes and changes the relationship: from then on they are not taking the
platform's word for its own evidence. Skipping it tends to mean nobody discovers
a verification problem until it matters.

### Step 6 — Wire webhooks

Subscribe to `scan.completed`, `review_case.opened` and `statement.status_changed`.
Verify signatures over raw bytes as described in `clients/WEBHOOKS.md`, and return
2xx quickly while doing the real work asynchronously.

`statement.status_changed` matters more than it first appears: it is how a
customer learns that evidence they already acted on has been superseded or
revoked. An integration that ignores it can keep relying on a withdrawn statement.

## 4. Support workflow

| Tier | Scope | Target response |
| --- | --- | --- |
| T1 | Usage questions, reading a result | 1 business day |
| T2 | Integration failures, webhook and credential issues | 4 business hours |
| T3 | Wrong decisions, coverage gaps, verification failures | 4 business hours, engineer attached |
| Sev-1 | Tenant isolation, key compromise, systematic false pass | 1 hour, continuous until resolved |

Every ticket starts with a correlation ID. Without one, the first reply asks for
it, because the alternative is guessing.

### Escalate to Sev-1 immediately for

- Any suspicion of cross-tenant data exposure.
- Any suspected signing-key compromise.
- Any `PASS_BY_POLICY` returned over non-`COMPLETE` coverage.
- Any statement that fails independent verification.

These four do not wait for business hours and are never downgraded to make a
metric look better.

## 5. Incident communication workflow

| Stage | Timing | Content |
| --- | --- | --- |
| Acknowledge | Within the response target | What is affected, what is not, who owns it |
| Update | Every 60 minutes while Sev-1 is open | What changed since the last update, even if nothing |
| Resolve | On fix | What happened, what was affected, what changed |
| Post-incident | Within 5 business days | Root cause, timeline, prevention |

Rules that hold under pressure:

- **Never state a cause before it is confirmed.** "We are investigating" is
  acceptable; a wrong cause has to be retracted and costs more trust than silence.
- **Name affected tenants and scans precisely.** Vague scope is read as a larger
  problem than the real one.
- **Say what customers should do**, including "no action required" when true.
- **Report evidence integrity separately from availability.** An outage is
  inconvenient; a statement that does not verify is a different category of
  problem and must never be folded into a general status note.
- **Notify on suspected key compromise even before it is confirmed**, along with
  the affected time window. Every statement signed in that window is in question,
  and customers need that window to make their own decisions.

### For a signing-key compromise, additionally

1. Follow the compromise runbook in `BLOCKCHAIN_GOVERNANCE_AND_TRUST.md`.
2. Publish the revocation and the new key in the trust bundle.
3. State the exact affected window.
4. Confirm that statements outside the window still verify, and show how to check.

## 6. Rollback

Every promoted model and every policy version is rollable.

| Artifact | Mechanism | Verify by |
| --- | --- | --- |
| Model bundle | Repoint to the previous `model_bundles` row | Scan a known fixture, compare the packet |
| Policy version | Activate the previous immutable version | Dry-run against historical scans first |
| Schema | `scripts/migrate.py downgrade` after a verified backup | API starts and serves reads |
| Signing key | Rotate forward; never reuse a retired key | Old statements still verify |

Model and policy identities are recorded in every evidence packet, so a rollback
is auditable after the fact: any packet states which bundle and which policy
version produced it. Drill this quarterly and record the elapsed time; an
untested rollback is an assumption.
