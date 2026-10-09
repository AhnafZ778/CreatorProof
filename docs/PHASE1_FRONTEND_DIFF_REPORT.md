# Phase 1 frontend diff report

> Historical result from the backend-only phase. The subsequently authorized
> [frontend integration](FRONTEND_INTEGRATION_REPORT.md) intentionally changes
> `apps/web`. The original baseline and JSON comparison remain byte-for-byte
> preserved. Running the legacy guard on today's frontend reports those new
> changes; it is not a pass criterion for the later frontend phase.

Phase 1 introduced no changes under `apps/web` relative to its recorded starting
worktree. The comparison covers tracked and untracked source-file membership and
SHA-256 byte hashes, including the user's pre-existing modified frontend files.

| Check | Result |
|---|---|
| Compared source files | 105 |
| Changed paths | 0 |
| Added paths | 0 |
| Removed paths | 0 |
| Frontend unchanged | true |

The frozen [baseline](phase1-frontend-baseline.json) and
[JSON comparison](phase1-frontend-verification.json) contain the checked paths
and outcome. Reproduce from the repository root:

```bash
python3 scripts/phase1_frontend_guard.py
```

The command uses `git ls-files --cached --others --exclude-standard -- apps/web`
to collect source membership, then compares current hashes with the baseline.
It fails on any changed, added or removed source file.

`git diff HEAD -- apps/web` includes earlier frontend work that existed before
Phase 1. Those differences were preserved; they are not changes introduced by
this implementation. The hash comparison and integration test verify the actual
Phase 1 boundary without discarding the user's earlier work.

Backend routes and fields are additive. Existing user/Admin/scan packet flows
are included in the backend regression suite. No frontend build or browser
redesign is claimed for this backend-only phase.
