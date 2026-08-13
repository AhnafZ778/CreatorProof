# CreatorProof benchmark workspace

This directory stores versioned metadata and report contracts. Raw media is external,
authorized, access-controlled, and addressed by SHA-256. Reports belong under
reports, which should contain only non-sensitive metrics and identifiers.

## Integrity rules

- Source lineage cannot cross train, calibration, test, or demo partitions.
- Exact bytes cannot occur in more than one partition.
- Final test assets are NEVER_SEEN before the locked run.
- Demo-exposed assets never become final-test evidence.
- Every item has a rights/permission reference.
- Creator-profile items require CONFIRMED consent.
- Thresholds are selected from calibration, never from final test.
- Every report binds manifest, ModelBundle, threshold policy, and prediction rows by
  digest.

Every lane-specific benchmark input must include corpus_manifest_paths, a list of
safe paths relative to that input file. Every referenced image path must appear in a
manifest for the same lane and required partition. Inputs without this binding may
still exercise code, but are forcibly labelled SMOKE_TEST_ONLY regardless of sample
count. Calibration fitting rejects legacy unbound score manifests completely.

The canonical corpus and profile schemas are under model_lab/schemas. Generic
prediction and report schemas are under benchmarks/schemas.

## Structural verification

The example manifests contain placeholder metadata and no media. They validate the
split contract only and are not a lawful demo corpus:

    python -m scripts.validate_benchmark_manifests \
      benchmarks/manifests/examples/copy-calibration.structural.v1.json \
      benchmarks/manifests/examples/copy-test.structural.v1.json

Validate a generated report:

    python -m scripts.validate_benchmark_report path/to/report.json

Run the fixed generated-media regression benchmark with the pinned SSCD artifact:

    python -m scripts.benchmark_model_system_stress --device cpu

That command compares algorithm versions on deterministic generated geometry. Its
grade is `SYNTHETIC_STRESS_ONLY_NOT_REAL_WORLD_ACCURACY`; it cannot substitute for an
authorized, lineage-disjoint test corpus.

Evaluate a sealed report against the proposed acceptance gates:

    python -m scripts.evaluate_model_acceptance path/to/report.json \
      --policy model_lab/policies/acceptance-policy.proposed.v1.json

The proposal is deliberately unratified, so it fails promotion closed. Ratification,
external terms/data/rehearsal approvals, and a human promotion record remain separate.

## Metric preregistration

Before opening final-test predictions, record:

| Lane | Primary metrics | Required slices | Stop condition |
| --- | --- | --- | --- |
| Copy retrieval | top-1, recall at 5, negative false-alert rate | transform, source, hard-negative cohort | leaked lineage or unsafe miss/false match |
| Copy verification | recall, precision, FPR, Wilson intervals, review rate | transform, geometry quality, partial/full | hard negative validates as copy |
| AI origin | ROC AUC, AP, operating points, abstention, selective accuracy | generator, real source, delivery transform | human inference from missing/quiet evidence |
| Creator profile | top-1, recall at k, verification AUC/EER, open-set rejection | profile size, creator, tradition, content confound | forced confident known profile or no consent |

Record exact confidence-interval method, thresholds, minimum support, domain,
exclusions, and claim wording. Meeting a sample-count gate does not prove data
independence or quality.
