# Component card: Tesseract visible AI-marker observation

## Role

Tesseract examines visible text for explicit AI-use labels or configured generator
marks. It produces forgeable review evidence only. It is not signed provenance and
cannot authenticate origin.

## Identity boundary

- Component: origin-visible-marker
- Provider: tesseract-visible-ai-marker-v1
- Preprocessing: VISIBLE_MARKER_MULTIVIEW_GRAYSCALE_V1
- Binary, language data, and configured term set must be recorded by the operator
- Current qualification: SOURCE_VERIFIED

## Known limits

Labels can be copied, removed, translated, stylized, cropped, or misread. A missing
label never means human-made. English is the current configured OCR language; broader
language claims require a separately authorized and measured evaluation.
