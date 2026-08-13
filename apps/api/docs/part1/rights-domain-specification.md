# Rights domain specification

This is a technical routing contract, not legal advice. It describes declared facts
and how CreatorProof handles missing or unsafe facts. It does not establish whether
the declarations are legally true.

## Facts that must remain separate

| Fact | Meaning | Never infer from |
| --- | --- | --- |
| Identity | A verified person or organization | Name string, style, or visual match |
| Relationship | Link between claimant, creator, and asset | Claimant string |
| Authorship | Who created the work | Detector, C2PA absence, or profile resemblance |
| Ownership | Who owns a defined right | Copy evidence or authorship assertion |
| Licensing authority | Who can grant a use | Uncorroborated claim |
| Permission | Whether this intended use fits declared terms | Generic pass label |

## Current implemented subset

Each registered Work currently records rights path, allowed-use identifiers, claimant
label, and claim state. A pass for a matched work requires:

1. complete evidence scope;
2. an EXISTING_LICENSE rights path;
3. a CORROBORATED claim state;
4. exact membership of the requested intended-use identifier in allowed uses.

Disputed rights, asserted/disputed/superseded/revoked claims, invalid values, missing
records, and out-of-scope uses route to review. LICENSE_AVAILABLE means a path may
exist but does not itself authorize the requested use.

## Normalized Part 2 assertion

Persistence should version an immutable assertion with:

- assertion ID and version;
- subject asset/work ID;
- asserting party and independently verified identity/relationship references;
- claim state and evidence references;
- rights or permission type;
- territory, effective start/end, channels, audience, purpose, and transformation
  scope;
- attribution, approval, reporting, and payment duties;
- allowed and prohibited use identifiers;
- dispute, supersession, revocation, and expiration metadata;
- created-by, created-at, policy-effective-at, and prior-version link.

Unknown facts remain null/unknown and fail toward review. Historical packets retain the
facts and policy version evaluated at scan time. Revocation affects future evaluations
without rewriting old evidence.

## State semantics

- ASSERTED: recorded statement, insufficient to authorize.
- CORROBORATED: enough referenced support for the selected technical policy to rely on;
  still not a court determination.
- DISPUTED: challenged; cannot authorize.
- SUPERSEDED: replaced by a newer assertion; cannot authorize future use.
- REVOKED: withdrawn or invalidated; cannot authorize future use.

## Non-match policy

A complete no-match may pass the selected pre-publication policy because no registered
catalog rights path was triggered. It always carries PASS_IS_POLICY_NOT_COPYRIGHT_CLEARANCE.
Incomplete scope cannot take this path.
