#!/usr/bin/env python3
"""Sanity-check the two architecture-pack PDFs after a Chrome render.

Confirms page count, file size, no trailing blank sheets, and that no text
block is drawn past the page edge — the usual overflow failure mode of these
landscape documents.
"""

from __future__ import annotations

from pathlib import Path

import fitz

HERE = Path(__file__).resolve().parent
PACKS = HERE / "architecture-packs"

EXPECTED = {
    "CreatorProof-BCOLBD-2026-Blockchain-Architecture.pdf": 18,
    "CreatorProof-BCOLBD-2026-AI-Architecture.pdf": 18,
}

LIMIT_MB = 20
# A4 landscape in points.
PAGE_W, PAGE_H = 841.89, 595.28
# Allow a hair of rounding past the physical edge.
SLACK = 2.0


def page_is_blank(page: fitz.Page) -> bool:
    if page.get_text().strip():
        return False
    return len(page.get_drawings()) <= 2


def overflow_blocks(page: fitz.Page) -> list[str]:
    hits: list[str] = []
    for block in page.get_text("blocks"):
        x0, y0, x1, y1, text, *_ = block
        if (
            x0 < -SLACK
            or y0 < -SLACK
            or x1 > PAGE_W + SLACK
            or y1 > PAGE_H + SLACK
        ):
            snippet = " ".join(text.split())[:72]
            hits.append(snippet)
    return hits


def check(path: Path, expected_pages: int) -> list[str]:
    problems: list[str] = []
    doc = fitz.open(path)
    pages = len(doc)
    size_mb = path.stat().st_size / 1_048_576

    if pages != expected_pages:
        problems.append(f"{pages} pages (expected {expected_pages})")
    if size_mb > LIMIT_MB:
        problems.append(f"{size_mb:.1f} MB exceeds the {LIMIT_MB} MB limit")
    if page_is_blank(doc[0]):
        problems.append("cover page is blank")
    if page_is_blank(doc[-1]):
        problems.append("trailing blank page")

    for i, page in enumerate(doc, start=1):
        if abs(page.rect.width - PAGE_W) > 1 or abs(page.rect.height - PAGE_H) > 1:
            problems.append(
                f"page {i} is {page.rect.width:.0f}×{page.rect.height:.0f} pt, not A4 landscape"
            )
            break
        leaked = overflow_blocks(page)
        if leaked:
            problems.append(f"page {i} text past the edge: {leaked[0]!r}")

    first = " ".join(doc[0].get_text().split())[:80]
    last = " ".join(doc[-1].get_text().split())[:80]
    doc.close()

    status = "OK" if not problems else "FAIL"
    print(f"  {path.name:<52} {pages:>2} pages  {size_mb:.1f} MB  {status}")
    if problems:
        for item in problems:
            print(f"    - {item}")
    else:
        print(f"    cover: {first}")
        print(f"    last:  {last}")
    return problems


def main() -> int:
    print("Verifying architecture packs:")
    failed = 0
    for name, expected in EXPECTED.items():
        path = PACKS / name
        if not path.exists():
            print(f"  {name:<52} MISSING")
            failed += 1
            continue
        if check(path, expected):
            failed += 1
    if failed:
        print(f"Failed ({failed}).")
        return 1
    print("All packs passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
