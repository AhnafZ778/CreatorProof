# Sightengine-primary AI-origin detection

## Outcome

CreatorProof uses Sightengine's `genai` API as the primary AI-origin detector when both
API credentials are configured. The existing local detector family is retained as an
operational fallback. This is a routing change and an evidence-quality improvement; it
does not make any detector perfect or convert a vendor score into provenance.

## Private configuration

Put these values in `creatorproof/.env` or a deployment secret manager:

```dotenv
CREATORPROOF_SYNTHETIC_DETECTOR=auto
CREATORPROOF_SIGHTENGINE_API_USER=your-api-user
CREATORPROOF_SIGHTENGINE_API_SECRET=your-api-secret
CREATORPROOF_SIGHTENGINE_TIMEOUT_SECONDS=20
```

The browser never receives the credentials. CreatorProof posts the accepted original
media directly from the API process, avoiding a public media URL. The example
environment file intentionally leaves both values blank. The client-supplied filename
is not forwarded; a generic filename is inferred from the accepted image bytes.

## Request and evidence flow

```text
accepted original image bytes
        |
        v
Sightengine genai primary (one request)
        | success                         | operational failure
        v                                 v
global/category signals             local detector set
        |                                 |
        +---------------+-----------------+
                        v
        origin evidence, scorecard, policy trace
```

Successful low responses do not trigger fallback. Doing so would cherry-pick the
highest detector and make scores incomparable. Fallback is restricted to explicit
authentication, quota, timeout, network, service, or response-contract failures.

## Edited-image score repair

The former local fusion averaged the original image score with JPEG, resize, blur, and
crop scores. Mild edits can remove fragile forensic traces, so one strong original
response was often diluted below 0.10 by weaker transformed views.

Local aggregation now preserves the original signal and uses transformed/cropped views
only to measure resilience or add corroboration:

```text
aggregate = max(original, delivery-consensus, corroborated-spatial-consensus)
```

A strong but transformation-sensitive signal remains a review candidate and is labelled
as unstable. Sightengine receives the original media once and is not subjected to
CreatorProof-generated transformations, preventing paid-call multiplication and score
dilution.

## What is recorded

- primary/fallback provider role and route state;
- global AI-generation signal;
- allowlisted generator-category and secondary vendor cues when returned;
- original/delivery/spatial local diagnostics where applicable;
- transformation-resilience state;
- model, preprocessing, calibration, and evidence-family states;
- limitations, reason codes, and operational failures.

Raw vendor responses, media URLs, and credentials are not stored in the Evidence
Packet. Generator cues are clues supplied by the vendor, not proof of a particular
generator or pixel-level explanations of “what looks AI.”

## Verification

From `creatorproof/apps/api`:

```bash
.venv/bin/pytest -q tests/test_sightengine_detector.py tests/test_synthetic_origin.py
.venv/bin/python -m scripts.check_synthetic_ai
```

The test suite mocks the remote request and proves primary routing, one-request media
upload, response parsing, secret non-disclosure, no fallback on a valid low score,
fallback on operational failure, and original-score preservation. A real API smoke
test must use private credentials and approved media; it must never run from checked-in
fixtures containing a secret.
