# Product validation and demo rehearsal

## Current evidence state

No customer interview, timed reviewer study, or locked demo-machine rehearsal has been
performed by this implementation. No adoption, time-saving, accuracy, or comprehension
number may be invented from unit tests.

## Reviewer walkthrough protocol

Recruit participants who perform or supervise creative review. Obtain consent and do
not use confidential customer media. Ask each participant to complete the same cases
first with their normal workflow and then with CreatorProof; counterbalance order when
the sample allows.

Record separately:

- task completion and escalation choice;
- time to first decision and total review time;
- whether copy, origin, profile resemblance, rights, and proof were distinguished;
- whether no-match was understood as source-scoped;
- whether missing origin evidence was understood as unresolved;
- confidence and explanation usefulness;
- disagreements, unsafe interpretations, and requested missing facts.

The report must include participant count, role mix, task corpus, denominators, order,
limitations, and raw response coding. A tiny qualitative walkthrough is product
learning, not statistical validation.

## Demo-machine rehearsal

Record:

- immutable bundle and manifest digest;
- application revision and runtime-lock digest;
- OS, CPU/GPU, RAM, Python, Node, browser, and display setup;
- exact active/unavailable providers;
- one cold and at least three warm full scans;
- acceptance latency, total latency, peak memory where practical, and failures;
- no-network behavior and one intentional optional-provider outage;
- expected packet/fixture diff for every scenario.

## Stop conditions

Stop promotion and label the result experimental if:

- any asset lacks a lawful use record;
- a model or checkpoint has unresolved event/product terms;
- a required artifact, hash, runtime lock, or profile consent mismatches;
- source lineage leaks across partitions;
- a hard negative becomes a geometry-supported match;
- absent origin evidence is shown as human;
- a reviewer interprets style as copying or proof as ownership;
- required learned retrieval becomes incomplete but the UI still reassures.

## Result template

State what was observed, the exact denominator, and the declared domain. Separate:

- software correctness from model quality;
- model benchmark metrics from reviewer workflow metrics;
- smoke tests from held-out evaluation;
- local receipt availability from public-chain anchoring;
- known limitations from future work.
