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
  local out="$here/$2.pdf"
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

echo "Rendering submission documents:"
render submission-answers "CreatorProof-Submission-Dossier"
render business-model "CreatorProof-Business-Model"
echo "Done."
