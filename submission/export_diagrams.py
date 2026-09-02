#!/usr/bin/env python3
"""Export every architecture-pack diagram as a standalone SVG and a 300-DPI PNG.

The diagrams are authored as CSS-styled inline SVG. This script copies each
<figure class="dia"> out of the HTML, injects the shared arrowhead markers and
the SVG vocabulary from arch.css, and writes a self-contained .svg. Chrome then
renders the same markup to PNG at print resolution so the files drop straight
onto a poster board or a pitch-deck slide.

Usage:
    python3 export_diagrams.py
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ASSETS = HERE / "assets"
SRC = HERE / "src"
OUT = HERE / "architecture-packs" / "diagrams"
CHROME = os.environ.get("CHROME", "google-chrome")

# Printed diagram column is 267 mm wide (A4 landscape minus the page-frame
# gutters). 300 DPI on that width is the poster/deck export size.
PRINT_WIDTH_MM = 267.0
DPI = 300
PX_PER_MM = DPI / 25.4

PACKS = (
    ("bcolbd-2026-blockchain-architecture.html", "blockchain"),
    ("bcolbd-2026-ai-architecture.html", "ai"),
)

# Fonts are two directories up from diagrams/<pack>/file.svg
FONT_URL = "../../assets/fonts"

EMBEDDED_CSS = f"""
@font-face {{
  font-family: "Geist";
  src: url("{FONT_URL}/GeistVariable.woff2") format("woff2-variations");
  font-weight: 100 900;
}}
@font-face {{
  font-family: "Geist Mono";
  src: url("{FONT_URL}/GeistMonoVariable.woff2") format("woff2-variations");
  font-weight: 100 900;
}}
@font-face {{
  font-family: "Space Grotesk";
  src: url("{FONT_URL}/SpaceGroteskVariable.woff2") format("woff2-variations");
  font-weight: 300 700;
}}
:root {{
  --bg: #05070c;
  --line: rgba(255, 255, 255, 0.11);
  --line-strong: rgba(255, 255, 255, 0.2);
  --text: #ffffff;
  --text-2: rgba(255, 255, 255, 0.74);
  --text-3: rgba(255, 255, 255, 0.54);
  --text-4: rgba(255, 255, 255, 0.36);
  --accent: #60a5fa;
  --accent-2: #a5b4fc;
  --pass: #34d399;
  --review: #fbbf24;
  --block: #f87171;
  --copy: #37d4dc;
  --origin: #f07ab7;
  --profile: #ffbd59;
  --sans: "Geist", ui-sans-serif, system-ui, sans-serif;
  --mono: "Geist Mono", ui-monospace, monospace;
  --display: "Space Grotesk", "Geist", sans-serif;
}}
svg {{ background: var(--bg); }}
svg text {{ font-family: var(--sans); fill: var(--text-2); }}
.nd {{ fill: rgba(255, 255, 255, 0.05); stroke: var(--line-strong); stroke-width: 1.4; }}
.nd-a {{ fill: rgba(96, 165, 250, 0.11); stroke: var(--accent); stroke-width: 1.6; }}
.nd-copy {{ fill: rgba(55, 212, 220, 0.1); stroke: var(--copy); stroke-width: 1.6; }}
.nd-orig {{ fill: rgba(240, 122, 183, 0.1); stroke: var(--origin); stroke-width: 1.6; }}
.nd-prof {{ fill: rgba(255, 189, 89, 0.1); stroke: var(--profile); stroke-width: 1.6; }}
.nd-pass {{ fill: rgba(52, 211, 153, 0.1); stroke: var(--pass); stroke-width: 1.6; }}
.nd-warn {{ fill: rgba(251, 191, 36, 0.1); stroke: var(--review); stroke-width: 1.6; }}
.nd-bad {{ fill: rgba(248, 113, 113, 0.1); stroke: var(--block); stroke-width: 1.6; }}
.nd-ghost {{ fill: none; stroke: var(--line); stroke-width: 1.2; stroke-dasharray: 6 5; }}
.zone {{ fill: rgba(255, 255, 255, 0.018); stroke: var(--line); stroke-width: 1.1; stroke-dasharray: 7 6; }}
.zone-private {{ fill: rgba(255, 255, 255, 0.028); stroke: var(--line-strong); stroke-width: 1.1; }}
.zone-public {{ fill: rgba(96, 165, 250, 0.055); stroke: var(--accent); stroke-width: 1.2; stroke-dasharray: 8 6; }}
.t-title {{ font-size: 21px; font-weight: 600; fill: var(--text); }}
.t-sub {{ font-size: 16.5px; fill: var(--text-3); }}
.t-body {{ font-size: 17.5px; fill: var(--text-2); }}
.t-lbl {{ font-family: var(--mono); font-size: 14px; font-weight: 600; fill: var(--text-4); letter-spacing: 1.5px; text-transform: uppercase; }}
.t-mono {{ font-family: var(--mono); font-size: 15px; fill: var(--text-3); }}
.t-big {{ font-family: var(--display); font-size: 30px; font-weight: 500; fill: var(--text); }}
.fx-a {{ fill: var(--accent); }}
.fx-copy {{ fill: var(--copy); }}
.fx-orig {{ fill: var(--origin); }}
.fx-prof {{ fill: var(--profile); }}
.fx-pass {{ fill: var(--pass); }}
.fx-warn {{ fill: var(--review); }}
.fx-bad {{ fill: var(--block); }}
.fx-dim {{ fill: var(--text-4); }}
.fx-txt {{ fill: var(--text); }}
.ar {{ fill: none; stroke: var(--line-strong); stroke-width: 1.6; }}
.ar-dec {{ fill: none; stroke: var(--accent); stroke-width: 1.8; }}
.ar-sig {{ fill: none; stroke: var(--accent-2); stroke-width: 1.6; stroke-dasharray: 7 5; }}
.ar-pub {{ fill: none; stroke: #7fb3ff; stroke-width: 3.2; }}
.ar-bad {{ fill: none; stroke: var(--block); stroke-width: 1.8; stroke-dasharray: 5 5; }}
.ar-soft {{ fill: none; stroke: var(--line); stroke-width: 1.3; stroke-dasharray: 4 4; }}
.rule {{ stroke: var(--line-strong); stroke-width: 1.2; }}
.rule-hot {{ stroke: #7fb3ff; stroke-width: 2; stroke-dasharray: 10 6; }}
.cal circle {{ fill: #05070c; stroke: var(--accent); stroke-width: 1.8; }}
.cal text {{ font-family: var(--mono); font-size: 16px; font-weight: 700; fill: var(--accent); text-anchor: middle; }}
""".strip()


def extract_markers(html: str) -> str:
    match = re.search(
        r'<svg[^>]*aria-hidden="true"[^>]*>\s*<defs>(.*?)</defs>\s*</svg>',
        html,
        re.S,
    )
    if not match:
        raise SystemExit("shared arrowhead <defs> not found")
    return match.group(1).strip()


def extract_diagrams(html: str) -> list[tuple[str, str, str]]:
    """Return (slide_id, svg_inner, caption) for every figure.dia."""
    found: list[tuple[str, str, str]] = []
    sections = re.finditer(
        r'<section class="slide" id="([^"]+)">(.*?)(?=<section class="slide"|$)',
        html,
        re.S,
    )
    for section in sections:
        slide_id = section.group(1)
        body = section.group(2)
        figure = re.search(
            r'<figure class="dia">\s*(<svg\b.*?</svg>)\s*<figcaption>(.*?)</figcaption>',
            body,
            re.S,
        )
        if not figure:
            continue
        svg = figure.group(1)
        caption = re.sub(r"\s+", " ", figure.group(2)).strip()
        found.append((slide_id.upper(), svg, caption))
    return found


def viewbox_size(svg: str) -> tuple[float, float]:
    match = re.search(r'viewBox="0 0 ([\d.]+) ([\d.]+)"', svg)
    if not match:
        raise SystemExit("diagram is missing a 0 0 W H viewBox")
    return float(match.group(1)), float(match.group(2))


def standalone_svg(raw_svg: str, markers: str, caption: str) -> str:
    width, height = viewbox_size(raw_svg)
    # Keep the original opening tag attributes, then inject xmlns / style / defs.
    opening = re.match(r"<svg\b([^>]*)>", raw_svg, re.S)
    if not opening:
        raise SystemExit("could not parse <svg> opening tag")
    inner = raw_svg[opening.end() : raw_svg.rfind("</svg>")].strip()
    attrs = opening.group(1)
    if "xmlns=" not in attrs:
        attrs = ' xmlns="http://www.w3.org/2000/svg"' + attrs
    if "overflow=" not in attrs:
        attrs += ' overflow="visible"'
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>\n'
        f"<!-- {caption} -->\n"
        f"<svg{attrs} width='{width}' height='{height}'>\n"
        f"  <style><![CDATA[\n{EMBEDDED_CSS}\n]]></style>\n"
        f"  <defs>\n{markers}\n  </defs>\n"
        f"  {inner}\n"
        f"</svg>\n"
    )


def screenshot(html_path: Path, png_path: Path, width_px: int, height_px: int) -> None:
    cmd = [
        CHROME,
        "--headless=new",
        "--disable-gpu",
        "--no-sandbox",
        "--hide-scrollbars",
        "--force-device-scale-factor=1",
        f"--window-size={width_px},{height_px}",
        "--default-background-color=05070cff",
        "--virtual-time-budget=4000",
        f"--screenshot={png_path}",
        html_path.as_uri(),
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def png_wrapper(svg_markup: str, css_href: str, width_px: int, height_px: int) -> str:
    # Strip the XML declaration so the fragment is valid HTML, then force the
    # rendered pixel size so Chrome's screenshot matches the requested DPI.
    body_svg = re.sub(r"^<\?xml[^>]*>\s*", "", svg_markup)
    body_svg = re.sub(
        r" width='[\d.]+' height='[\d.]+'",
        f' width="{width_px}" height="{height_px}"',
        body_svg,
        count=1,
    )
    return f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8">
<link rel="stylesheet" href="{css_href}">
<style>
  html, body {{ margin: 0; padding: 0; background: #05070c; overflow: hidden; width: {width_px}px; height: {height_px}px; }}
  svg {{ display: block; background: #05070c; }}
</style>
</head><body>
{body_svg}
</body></html>
"""


def export_pack(html_name: str, pack_dir: str) -> int:
    html_path = SRC / html_name
    html = html_path.read_text(encoding="utf-8")
    markers = extract_markers(html)
    diagrams = extract_diagrams(html)
    dest = OUT / pack_dir
    dest.mkdir(parents=True, exist_ok=True)

    css_href = ASSETS.joinpath("arch.css").as_uri()
    pad = 24  # keep overflowing callout badges inside the PNG frame

    with tempfile.TemporaryDirectory(prefix="cp-dia-") as tmp:
        tmp_path = Path(tmp)
        for slide_id, raw_svg, caption in diagrams:
            svg_text = standalone_svg(raw_svg, markers, caption)
            svg_out = dest / f"{slide_id}.svg"
            svg_out.write_text(svg_text, encoding="utf-8")

            vb_w, vb_h = viewbox_size(raw_svg)
            width_px = round(PRINT_WIDTH_MM * PX_PER_MM)
            height_px = round(width_px * (vb_h / vb_w)) + pad

            wrapper = tmp_path / f"{slide_id}.html"
            wrapper.write_text(
                png_wrapper(svg_text, css_href, width_px, height_px),
                encoding="utf-8",
            )
            png_out = dest / f"{slide_id}.png"
            screenshot(wrapper, png_out, width_px, height_px)
            print(f"  {pack_dir}/{slide_id:<4}  SVG + {width_px}×{height_px} PNG @ {DPI} DPI")

    return len(diagrams)


def main() -> int:
    if shutil.which(CHROME) is None:
        raise SystemExit(f"Chrome not found ({CHROME}). Set CHROME= to the binary.")
    OUT.mkdir(parents=True, exist_ok=True)
    print(f"Exporting diagrams at {DPI} DPI ({PRINT_WIDTH_MM:.0f} mm column):")
    total = 0
    for html_name, pack_dir in PACKS:
        total += export_pack(html_name, pack_dir)
    print(f"Done. {total} diagrams in {OUT.relative_to(HERE)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
