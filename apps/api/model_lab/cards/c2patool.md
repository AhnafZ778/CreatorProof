# Component card: c2patool provenance inspection

## Role

The official c2patool adapter inspects Content Credentials from the original
candidate bytes. Provenance is kept separate from passive pixel detection and visible
text labels.

## Distinct facts

The packet reports manifest presence, manifest validity, signature validity, signer
trust, relevant AI assertion presence, ingredient-chain state, and trust-policy
identity separately. A valid but untrusted signer is not presented as trusted.

No manifest is neutral unknown provenance and always carries the boundary that absence
does not establish human origin. Invalid or unreadable output is an error or invalid
state, never a negative AI result.

## Identity and current state

- Component: origin-c2pa
- Provider: c2patool-official
- Input preprocessing: ORIGINAL_CANDIDATE_BYTES_V1
- Binary version and trust configuration: operator-installed and must be recorded
- Current component qualification: SOURCE_VERIFIED until binary/version/trust preflight is enforced

## Promotion requirements

Pin the c2patool binary/container version, document trust roots and policy ID, test
absent, valid-untrusted, trusted, invalid, malformed, timeout, and AI-assertion cases,
and preserve raw-media privacy.
