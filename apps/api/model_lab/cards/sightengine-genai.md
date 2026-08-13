# Sightengine `genai` API

## Role

Sightengine is the preferred remote AI-origin signal when both server-side credentials
are configured. CreatorProof sends the accepted original image once to the `genai`
endpoint and records the returned global signal plus any generator-category signals.

## Identity boundary

- Component: `origin-sightengine-genai`
- Provider: `sightengine-genai`
- Preprocessing: `SIGHTENGINE_GENAI_ORIGINAL_MEDIA_UPLOAD_V1`
- Runtime identity: vendor-managed API, not a locally pinned artifact
- Qualification: `SOURCE_VERIFIED`
- Calibration: not configured for CreatorProof's deployment domain

The provider model can change without a CreatorProof source or artifact change. A
successful API call therefore proves which service contract was used, not immutable
model bytes.

## Routing contract

1. `auto` and `sightengine` modes select Sightengine as primary when both credentials
   are present.
2. A successful response is authoritative for that provider call, including a low
   score. Local models are not run to shop for a higher result.
3. Authentication, quota, timeout, network, service, or invalid-response failures
   activate the configured local detector set as an explicit fallback.
4. The packet records primary success/failure, fallback activation, provider role, and
   operational error codes without recording credentials or raw vendor payloads.

## Permitted claims

- “Sightengine returned an AI-generation signal of X for this submitted image.”
- “The vendor response included these generator-category cues.”
- “CreatorProof routed this signal to review under the recorded policy.”

## Prohibited claims

- The score is the probability that the image is AI-generated.
- A low score proves human origin.
- A generator-category score proves which tool created the image.
- The API result is signed provenance, pixel-level attribution, or a legal conclusion.
- CreatorProof has independently validated accuracy without a sealed authorized report.

## Operational and privacy limits

The submitted media leaves the local system when this provider is active. Operators
must approve the service terms, privacy posture, retention behavior, lawful media use,
and credential handling before deployment. Credentials belong in a private `.env` or
secret manager, never `.env.example`, frontend code, logs, Evidence Packets, fixtures,
or screenshots.

## Fallback

Community Forensics, a configured TorchScript detector, and approved external detectors
remain local fallback candidates. Fallback indicates remote operational failure; it is
not evidence that the image is human-made and it is never silently blended with a
successful Sightengine result.
