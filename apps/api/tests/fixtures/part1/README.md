# CreatorProof Part 1 contract fixtures

The file packet-scenarios.v1.json is the stable, model-independent handoff contract
for UI, proof, and persistence work. It contains expected packet fragments, not
benchmark predictions and not legal conclusions.

The referenced media is deliberately external. Before using a scenario in a public
demo, replace its placeholder rights reference with an owned, licensed, public-domain
verified, or explicitly authorized asset record and bind that media by SHA-256 in a
corpus manifest.

Verification command:

    pytest -q tests/test_part1_contract_fixtures.py

The test enforces the safety invariants shared with Part 2: incomplete scope cannot
pass, missing provenance cannot imply human origin, style cannot create a copy match,
and disputed/revoked claims cannot authorize use.
