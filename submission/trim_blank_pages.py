#!/usr/bin/env python3
"""Drop trailing pages that carry no ink, then report the result.

These documents print on a black background, so "blank" cannot mean "white".
A page counts as blank when it has no text and no drawing beyond the single
full-bleed background rectangle the page frame paints on every sheet.
"""

from __future__ import annotations

import sys

import fitz


def page_is_blank(page: fitz.Page) -> bool:
    if page.get_text().strip():
        return False
    # One or two drawings is the background fill and the frame table's borders;
    # anything more means real content.
    return len(page.get_drawings()) <= 2


def main(path: str) -> int:
    doc = fitz.open(path)
    removed = 0

    while len(doc) > 1 and page_is_blank(doc[len(doc) - 1]):
        doc.delete_page(len(doc) - 1)
        removed += 1

    if removed:
        doc.save(path, incremental=False, deflate=True, garbage=3)

    pages = len(doc)
    size_mb = doc.tobytes(deflate=True, garbage=3).__len__() / 1_048_576
    doc.close()

    name = path.rsplit("/", 1)[-1]
    trailer = f"  (trimmed {removed} blank)" if removed else ""
    print(f"  {name:<46} {pages:>2} pages  {size_mb:.1f} MB{trailer}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
