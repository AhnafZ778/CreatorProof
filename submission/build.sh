#!/usr/bin/env bash
# Render the submission HTML sources to PDF with headless Chrome.
#
# Chrome is used rather than a Python PDF library because these documents rely
# on the product's own CSS tokens and self-hosted variable fonts; a browser
# engine is the only renderer that reproduces them faithfully.
#
# The page frame in doc.css uses a repeating table footer to create the bottom
# margin, which occasionally spills one empty sheet past the end of the
# content. The post-pass below drops any trailing page that has no ink on it.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
chrome="${CHROME:-google-chrome}"

render() {
  local src="$here/src/$1.html"
  local out="${3:-$here}/$2.pdf"
  "$chrome" \
    --headless=new \
    --disable-gpu \
    --no-sandbox \
    --no-pdf-header-footer \
    --virtual-time-budget=10000 \
    --print-to-pdf="$out" \
    "file://$src" 2>/dev/null
  python3 "$here/trim_blank_pages.py" "$out"
}

packs="$here/architecture-packs"

echo "Rendering submission documents:"
render submission-answers "CreatorProof-Submission-Dossier"
render business-model "CreatorProof-Business-Model"
render ai-ideathon-2026 "CreatorProof-AI-Ideathon-2026-Submission"
render bcolbd-2026-ai-explained "CreatorProof-AI-Explained-Plain-English"
render bcolbd-2026-blockchain-explained "CreatorProof-Blockchain-Explained-Plain-English"

# The two architecture packs are A4 landscape rather than portrait and are
# presented from directly, so they live beside their design notes.
echo "Rendering architecture packs:"
render bcolbd-2026-blockchain-architecture "CreatorProof-BCOLBD-2026-Blockchain-Architecture" "$packs"
render bcolbd-2026-ai-architecture "CreatorProof-BCOLBD-2026-AI-Architecture" "$packs"

echo "Exporting diagrams (SVG + 300-DPI PNG):"
python3 "$here/export_diagrams.py"

echo "Verifying architecture packs:"
python3 "$here/verify_architecture_packs.py"
echo "Done."
