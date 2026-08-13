# Part 1 implementation status

## Engineering outcome

The code-completable Part 1 foundation is implemented. The selected local runtime is
RUNTIME_READY, bound to exact package and requirement-file identities, and fail-visible.
Part 1 is not yet competition-complete because lawful
empirical data, organizer decisions, user validation, terms approval, and final demo
rehearsal require external evidence that software cannot manufacture.

The v0.10.0 hardening pass additionally implements sealed report validation,
acceptance-policy evaluation, identity-safe atomic caches, durable Redis job recovery,
regional SSCD retrieval, geometry-support-aware structural scoring, selected-profile
multiplicity correction, lineage-clustered uncertainty, runtime telemetry, and drift
triggers. The final Sprint 1 pass restores those contracts after the platform merge,
adds Sightengine-primary AI-origin routing with operational local fallback, preserves
strong original-image signals during local transformation analysis, and exposes a
cleaner judge-facing evidence route. Its deterministic generated-media suite is a
regression stress test, not a replacement for the still-missing authorized test corpus.

| Phase | Engineering status | External gate |
| --- | --- | --- |
| P0 scope and claims | Implemented in scope, claim, scenario, and ADR documents | Owner/organizer approval |
| P1 reproducible runtime | Implemented; bundle, source, lock, artifacts, preflight, probes | Required terms approval before demo promotion |
| P2 corpus/evaluation | Schemas, validators, binding, report identity implemented | Acquire lawful media and run locked reports |
| P3 product evidence | Protocol and stop conditions implemented | Conduct interviews/walkthroughs; no metrics claimed yet |
| P4 copy quality | Fail-closed fusion preserved; bounded exhaustive verification added | Run transformation/hard-negative held-out report |
| P5 origin/provenance | Trust facts, artifact calibration binding, executable check, Sightengine-primary route, local failure fallback, and provider cues implemented | Approve remote-service terms/privacy; calibrate lawful domain; repair/approve optional second local family |
| P6 creator profile | Consent/version registry and escalation gate implemented | Enroll consenting creators and run open-set evaluation |
| P7 rights policy | Specification, golden cases, deterministic trace implemented | Counsel/product review and Part 2 normalized persistence |
| P8 handoff | Ten fixtures, contract, cards, registries, and handoff implemented | Agent B compatibility review |
| P9 competition package | Rehearsal protocol and technical checks available | Run final machine/media rehearsal and produce empirical assets |

## Verification entry points

From apps/api:

    python -m scripts.validate_model_bundle --require-state RUNTIME_READY
    python -m scripts.preflight_part1 --require-state RUNTIME_READY
    python -m scripts.validate_benchmark_manifests \
      benchmarks/manifests/examples/copy-calibration.structural.v1.json \
      benchmarks/manifests/examples/copy-test.structural.v1.json
    python -m scripts.benchmark_model_system_stress --device cpu
    python -m scripts.evaluate_runtime_drift path/to/evidence-packets.json
    pytest -q
    ruff check app tests scripts
    ruff format --check app tests scripts

Optional selected-runtime probes:

    python -m scripts.check_ai --device cpu
    python -m scripts.check_synthetic_ai
    python -m scripts.check_style_ai --require-learned

These probes validate loading, identity, shape, and repeatability only. They are not
accuracy tests.

Sightengine is tested through a mocked contract suite so no credential or unapproved
media is sent during CI. A live smoke test requires private rotated credentials and an
operator-approved image. See `SIGHTENGINE-PRIMARY-DETECTION.md`.

## Promotion blockers

The bundle remains below DEMO_READY until all required rows are cleared:

- resolve and approve required artifact/data terms for the intended event;
- replace structural examples with authorized, digest-bound corpus manifests;
- run preregistered held-out copy results and honest origin/style reports;
- add confirmed profile consent for any demonstrated creator-profile lane;
- complete reviewer comprehension checks;
- complete final-machine cold/warm/no-network rehearsal;
- freeze expected packet fragments from the final bundle;
- receive Agent B contract acceptance.

No missing external result is represented as completed.
