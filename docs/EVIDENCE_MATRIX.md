# Evidence Matrix

The matrix is an immutable projection of the existing evidence packet, not a replacement packet or a legal verdict. Its packet hash identifies the source commitment. Scores retain their source semantics; retrieval rankings, inlier ratios, origin-model responses, and style scores are never averaged into a probability of infringement.

## APIs and storage

`GET /v1/scans/{scan_id}/evidence-matrix` requires `scans:read` and returns the latest persisted version, signals, coverage rows, reason codes, abstention, and recommended action. Pending or historical scans without a persisted projection return `409 EVIDENCE_MATRIX_NOT_FINALIZED`; they do not produce a fabricated final result.

`POST /v1/scans/{scan_id}/evidence-matrix/corrections` requires `review:write` and a bounded JSON `reason`. It reprojects the recorded packet with the current normalizer and appends a numbered matrix linked by `previous_matrix_id`. Earlier matrices/signals remain immutable. A correction does not permit a caller to fabricate provider results or change the underlying scan decision. Corrections and reads create audit events.

Storage uses `evidence_matrices`, `evidence_signals`, and `evidence_coverages`, all tenant-scoped. Finalization persists a matrix before candidate cleanup. Terminal pipeline failures/cancellation produce a failure packet and a `PROVIDER_FAILURE` matrix; queued/transient attempts are not finalized prematurely.

## Independent lanes

| Lane | Interpretation |
|---|---|
| COPY | Exact hashes, retrieval candidates, geometry, aligned perceptual checks, and copy fusion |
| ORIGIN | Detector outputs, origin assessment, and visible-marker inspection |
| PROVENANCE | Manifest inspection with validity and trust kept separate |
| CREATOR_PROFILE | Advisory resemblance; not artist identity |
| RIGHTS | Recorded assertions, licenses, and unresolved permission facts |
| POLICY | Deterministic publication outcome, not a legal conclusion |
| SOURCE_COVERAGE | Declared corpus scope and missing/unavailable sources |
| INTEGRITY | Packet identity, not ownership |

Every signal has identity, scan/matrix association, provider/version, type/status, score and semantics, confidence level, evidence quality, coverage status, reasons, artifact references, input hash, timestamps, error/fallback, and model/rule identity. Unknown versions/scores remain null. Current `started_at` and `completed_at` are scan acceptance and projection-finalization bounds; they are not per-provider stopwatch measurements. The existing packet runtime telemetry contains measured durations where instrumented.

Signal states are `SUPPORTED`, `UNSUPPORTED`, `INCONCLUSIVE`, `PROVIDER_UNAVAILABLE`, `ERROR`, `NOT_RUN`, and `NOT_APPLICABLE`. Coverage percent is 100 only when all represented signals in that lane have complete coverage. Null percentages are not silently treated as complete. A safe summary of unavailable signals accompanies lane states.

## Final evidence state and abstention

`SUPPORTED` means the scoped conclusion has support; it does not establish ownership or that all conceivable sources were checked. `PARTIALLY_SUPPORTED` preserves a supported independent finding while documenting missing optional lanes. `INCONCLUSIVE` covers unresolved correspondence, `CONTRADICTORY` covers detector disagreement, `INSUFFICIENT_COVERAGE` covers inadequate scope without supported copy evidence, and `PROVIDER_FAILURE` covers terminal pipeline failure.

The latter four states explicitly abstain and recommend `HUMAN_REVIEW`. Publication policy remains a separate recorded value. `legal_conclusion` is always null. An exact copy can be supported even when the AI-origin service is unavailable; an AI-origin indicator never creates a copy finding.

Retrieval scores alone remain inconclusive. Region references are emitted only for geometrically validated correspondence or an explicitly corroborated relaxed alignment. Failed validation yields no invented regions. `NO_VALIDATED_COPY_REGION` is scoped to the checked corpus and does not imply the image is original everywhere.

## Tests

Run `uv run pytest tests/test_phase1_evidence_provenance.py tests/test_scan_flow.py tests/test_provenance_contract.py` from `apps/api`. The integration tests verify persisted rows, eight lanes, packet commitment, zero-retention survival, append-only correction history, and unauthorized access; contract cases cover disagreement, semantic/style/AI-only evidence, failures, and insufficient scope.
