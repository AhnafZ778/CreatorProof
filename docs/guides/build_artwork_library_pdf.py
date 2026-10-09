#!/usr/bin/env python3
"""Build the CreatorProof Artwork Library visual walkthrough PDF."""

from pathlib import Path
from tempfile import TemporaryDirectory
from xml.sax.saxutils import escape

from PIL import Image
from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import Image as FlowImage, Paragraph


ROOT = Path(__file__).resolve().parents[2]
GUIDE = ROOT / "docs/guides/ARTWORK_LIBRARY_WALKTHROUGH.md"
IMAGE_DIR = ROOT / "docs/guides/artwork-library/images"
OUTPUT = ROOT / "docs/guides/ARTWORK_LIBRARY_WALKTHROUGH.pdf"
PAGE_W, PAGE_H = landscape(A4)

FONT_REGULAR = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
pdfmetrics.registerFont(TTFont("GuideSans", FONT_REGULAR))
pdfmetrics.registerFont(TTFont("GuideSans-Bold", FONT_BOLD))

INK = colors.HexColor("#F3F6FC")
MUTED = colors.HexColor("#AAB6CB")
BLUE = colors.HexColor("#66A8FF")
PANEL = colors.HexColor("#101827")
PANEL_LINE = colors.HexColor("#26364F")
BG = colors.HexColor("#070B12")

BODY = ParagraphStyle(
    "Body", fontName="GuideSans", fontSize=9.15, leading=13.1,
    textColor=INK, spaceAfter=7,
)
SMALL = ParagraphStyle(
    "Small", fontName="GuideSans", fontSize=8.25, leading=11.5,
    textColor=MUTED, spaceAfter=6,
)
BLOCK_TITLE = ParagraphStyle(
    "BlockTitle", fontName="GuideSans-Bold", fontSize=10.1, leading=13,
    textColor=BLUE, spaceBefore=2, spaceAfter=4,
)
CALLOUT = ParagraphStyle(
    "Callout", fontName="GuideSans", fontSize=8.65, leading=12,
    textColor=INK, leftIndent=7, borderColor=PANEL_LINE,
    borderWidth=0.7, borderPadding=7, backColor=colors.HexColor("#152238"),
    spaceBefore=2, spaceAfter=7,
)


def b(text: str) -> str:
    return f"<b>{text}</b>"


def bullet(text: str) -> str:
    return f"<font color='#66A8FF'>•</font> &nbsp;{text}"


PAGES = [
    {
        "label": "START HERE",
        "title": "Your Artwork Library, at a glance",
        "subtitle": "A visual guide to registering references, recording rights, and preparing evidence.",
        "image": "01-library-overview.png",
        "blocks": [
            ("What this page is", "The Artwork library holds an artist’s <b>registered reference works</b>. CreatorProof compares later candidate images against these references. Candidate scans and flagged cases belong in the User and Admin areas."),
            ("How to read the screen", "The left side is your collection: search, refresh, and select a work. The larger right workspace contains tools for that selected work. Its tabs are <b>Permissions</b>, <b>Creation history</b>, <b>Origin evidence</b>, and <b>Share &amp; export</b>."),
            ("Blue numbered markers", "<b>1</b> switches between the saved library and registration form. <b>2</b> filters by title or claimant. <b>3</b> reloads the list. <b>4</b> selects a reference card. <b>5</b> changes tools for the selected work. <b>6</b> opens registration."),
            ("A detail to remember", "Each card has its own workspace. Save a policy or history entry before selecting a different card. The selected work in these screenshots is named “Boy”; its values and the visible record count are example data from the captured local site."),
        ],
    },
    {
        "label": "1 · REGISTER A REFERENCE",
        "title": "Add the original artwork",
        "subtitle": "Register the reference image that future scans should compare against.",
        "image": "08-register-artwork.png",
        "blocks": [
            ("Fill out the form", "Open <b>Register artwork</b>. Drop an image in the upload area or browse for a PNG, JPG/JPEG, or WEBP file. The visible form accepts files up to <b>4 MB and 6 megapixels</b>; you can replace or remove the selection before submitting."),
            ("Name the work accurately", "Enter a clear <b>Artwork title</b> and the correct <b>Artist / claimant name</b>. The claimant may be prefilled from the current Artist portal. Correct it if the work belongs to another person or organization."),
            ("Review optional settings", "Usually leave <b>Advanced registration settings</b> unchanged. The normal catalog is <code>artist-library</code>. Available claim labels include Artist-recorded, Supporting record declared, Under review, and Withdrawn. Choose a supporting-record claim only when supporting records actually exist."),
            ("Screen, then submit", "Read the AI-origin screening notice and choose <b>Register reference</b>. If screening refuses the image, review the reason shown by the form. On success, the record receives an Artwork ID and image fingerprints."),
            ("Meaning of registration", "Registration records the artist’s claim; it does <b>not</b> independently establish copyright ownership. Passing origin screening does not prove that an image was made by a person."),
        ],
    },
    {
        "label": "2 · CATALOGS",
        "title": "Make scans search the right collection",
        "subtitle": "A scan searches one named catalog at a time. The names must match exactly.",
        "image": "09-registration-details.png",
        "blocks": [
            ("Check the saved record", "Open <b>Artwork registration details</b> under the selected work. <b>1</b> is the claimant, <b>2</b> the registration date, <b>3</b> the recorded claim state, <b>4</b> the catalog, and <b>5</b> the Artwork ID. Keep the ID for support or evidence workflows."),
            ("Match the catalog name", "The registration form and User scan form both default to <code>artist-library</code>. A work stored in <code>creatorproof-collection</code> will not be searched by a scan that uses <code>artist-library</code>. The library can display multiple catalogs together, so its total count is not the count a scan searches."),
            ("Before trusting a no-match", "Confirm the selected reference’s catalog matches the scan or monitor’s catalog. If a scan reports an empty catalog, check this first. “No match” means no supported reuse was found in the catalog and sources actually checked; it does not mean the image is unused everywhere."),
            ("Claim status in plain terms", "“Artist-recorded” means the claim was entered by the artist. It does not mean a third party verified ownership. The screenshot shows current saved data, not universal defaults."),
        ],
    },
    {
        "label": "3 · PERMISSIONS",
        "title": "Set the artist’s stated usage preferences",
        "subtitle": "The Rights Passport is a versioned record of what is allowed, restricted, or still needs review.",
        "image": "02-permissions-presets.png",
        "blocks": [
            ("Start with the saved version", "Check the policy <b>Version</b> and <b>Active</b> status. The refresh button reloads the saved policy. The screenshot shows the saved settings for “Boy”; those are not defaults for other works."),
            ("Quick starting choices", "A preset fills the controls but <b>does not save</b>. Review every field afterward. <b>License first</b> sets every permission to License required. <b>Allow discovery; license other uses</b> allows the two discovery settings and requires a license for the others. <b>Leave unspecified</b> records no preference."),
            ("What each choice means", "<b>Allowed</b> permits the stated use; <b>Not allowed</b> records that it is not permitted; <b>License required</b> asks for a separate license; <b>Ask for review</b> requires a person to review; <b>Not specified</b> records no preference and is not the same as Allowed; <b>Not applicable</b> means the setting does not apply to this work."),
            ("The four permission groups", "<b>Discovery:</b> Search indexing, Commercial search. <b>Training:</b> General AI training, Noncommercial training, Commercial training, Model fine-tuning. <b>Creation:</b> Style reference, Image-to-image, AI image editing, Generated derivatives. <b>Identity:</b> likeness use for a depicted person."),
            ("Then save a new version", "Expand groups, choose values that match the artist’s actual intent, add accurate license details if known, and save a new policy version. A preference is not a signed contract, legal ruling, or technical block on outside websites."),
        ],
    },
    {
        "label": "3 · PERMISSIONS",
        "title": "Scope each permission carefully",
        "subtitle": "The upper controls cover creation and identity permissions; lower controls add context and limits.",
        "image": "03-permissions-scope.png",
        "crop": (0, 0, 850, 660),
        "blocks": [
            ("Choose only what is known", "The numbered controls in this part of the screen are individual permission choices. Select an option separately for each use. Leave it <b>Not specified</b> if the artist has not decided or the information is not known."),
            ("Creation uses", "The Creation group records preferences for style reference, image-to-image use, AI editing, and generated derivatives. These are distinct uses: do not assume permission for one automatically covers the others."),
            ("Identity / likeness", "Identity covers likeness use for a depicted person. It is a different question from whether the artwork itself may be used. Record only a preference that the relevant person or authorized representative can make."),
            ("Do not overstate what a setting does", "These fields record the artist’s declared policy. They do not automatically notify a platform, grant a license, or enforce a restriction on an unrelated service."),
        ],
    },
    {
        "label": "3 · PERMISSIONS",
        "title": "Add credit, license, scope, and dates",
        "subtitle": "Specific values make a preference easier to interpret, but they do not make another party comply.",
        "image": "03-permissions-scope.png",
        "crop": (0, 620, 850, 1280),
        "blocks": [
            ("Attribution & licensing details", "Record whether credit is required, the exact credit wording, a licensing contact, and a minimum fee and currency when those details are known."),
            ("Advanced scope, consent & dates", "The lower fields can describe permitted countries, platforms, model identifiers, channels, audiences, transformations, consent status and source, effective dates, and a broad text/data-mining reservation."),
            ("Website path and notes", "The artwork path is a path on the artist’s website used by preference exports; the app does not fetch that URL. Policy notes can capture extra conditions or review instructions."),
            ("Good practice", "A country list, license fee, or model name narrows the recorded preference. Leave uncertain fields unspecified instead of guessing. Check the artist’s intent before saving."),
        ],
    },
    {
        "label": "3 · PERMISSIONS",
        "title": "Save, withdraw, and review policy history",
        "subtitle": "Policy edits create versions so you can see what was recorded over time.",
        "image": "04-permissions-history.png",
        "crop": (0, 600, 840, 1200),
        "blocks": [
            ("1 · Save new policy version", "Saving applies the choices and creates a new version. Earlier versions remain in the history. The screenshot is on Version 2; a new record can begin with unknown permissions."),
            ("2 · Withdraw this policy", "Withdrawal is a recorded action after confirmation. It preserves prior history. Review existing contracts separately; withdrawing a preference does not itself resolve those agreements."),
            ("Check before saving", "Read each setting, scope and contact detail. Presets are only starting points. Make sure you have not left a value that contradicts the artist’s intended policy."),
        ],
    },
    {
        "label": "3 · PERMISSIONS",
        "title": "Read earlier versions and claim records",
        "subtitle": "Exports and claims provide a record; they do not independently prove ownership.",
        "image": "04-permissions-history.png",
        "crop": (0, 1000, 840, 1676),
        "blocks": [
            ("3 · Previous versions & passport export", "Choose a version to view it read-only, or export the Rights Passport. A previous version helps explain what was recorded at an earlier point in time."),
            ("4 · Claims and licenses", "This area separates the artist’s assertion from corroborating evidence and recorded licenses. A self-declared claim is not independent verification. Review supporting records and license entries separately."),
            ("Keep the limits clear", "A Rights Passport is the artist’s recorded preference. It is not a court decision, a signed license contract, or a mechanism that forces unrelated websites to follow the preference."),
        ],
    },
    {
        "label": "4 · CREATION HISTORY",
        "title": "Record the real creative process",
        "subtitle": "Use the timeline to describe truthful steps, people, tools, and decisions.",
        "image": "05-creation-history.png",
        "crop": (0, 0, 890, 700),
        "blocks": [
            ("Integrity and existing events", "The top of the tab shows the integrity status and number of recorded events. An empty timeline is normal before you add anything. The screenshot says “Valid” for its current stored chain."),
            ("Verify and export", "<b>Verify history</b> checks whether the saved event hash chain is consistent. <b>Export history</b> downloads the record. “Valid” means the stored record passed that check; it does not prove the events are true or determine authorship."),
            ("Begin with a real step", "Examples include an original sketch, manual edit, AI-assisted step, human selection, or publication. Add events in chronological order and describe what actually happened."),
        ],
    },
    {
        "label": "4 · CREATION HISTORY",
        "title": "Describe who did what and when",
        "subtitle": "The event form keeps the human contribution and any tool assistance explicit.",
        "image": "05-creation-history.png",
        "crop": (0, 580, 890, 1280),
        "blocks": [
            ("1 · What happened?", "Choose the step type, such as original sketch or edit. <b>2 · Who performed this step?</b> records Human, AI, system, or unknown."),
            ("3 · Describe the step", "Explain it in ordinary language. Add the contribution classification, software or model, date, and the human’s decision where relevant. Say what the person selected, corrected, composed, or changed."),
            ("4 · Supporting assets and references", "Optional fields can store real asset IDs, input/output version IDs, provider and model versions, source/evidence references, Content Credentials references, and before/after SHA-256 hashes."),
            ("Private prompt reference", "If recording a prompt, use a private reference or hash. Do not paste a raw prompt into a field that asks for a private prompt reference."),
        ],
    },
    {
        "label": "4 · CREATION HISTORY",
        "title": "Add events; correct with another event",
        "subtitle": "Creation-history entries are append-only so the record retains its sequence.",
        "image": "05-creation-history.png",
        "crop": (0, 1120, 890, 2120),
        "blocks": [
            ("Add the event", "When the description is accurate, choose <b>Add event to history</b>. Record a real date if known; otherwise the form can use the current time. Do not invent process steps to fill an empty timeline."),
            ("Correcting an entry", "Entries are append-only. If an earlier event needs correction, add a new event that describes the correction rather than trying to rewrite the earlier record."),
            ("What integrity can tell you", "The hash-chain check helps show whether saved entries remain internally consistent. It cannot establish that a description is truthful or decide who owns copyright."),
            ("Useful habit", "Record important steps soon after they happen, with the tool/version and the human’s contribution while those details are still clear."),
        ],
    },
    {
        "label": "5 · ORIGIN EVIDENCE",
        "title": "Inspect provenance and metadata",
        "subtitle": "This panel reads embedded declarations and metadata; it is separate from copy matching.",
        "image": "06-origin-evidence.png",
        "crop": (0, 0, 890, 700),
        "blocks": [
            ("Content Credentials result", "The top result summarizes whether a supported Content Credentials manifest was found and inspected. A found manifest is not automatically valid or trusted."),
            ("Read the facts separately", "Manifest presence, manifest validity, signature validity, and signer trust are distinct facts. One does not imply the others. Declared creation and editing shows actions or models in a supported manifest, when present."),
            ("Not the copy detector", "Origin evidence is not the AI-origin detector and is not the artwork-copy comparison. Use the relevant scan and assessment panels for those separate questions."),
        ],
    },
    {
        "label": "5 · ORIGIN EVIDENCE",
        "title": "Understand an absent result",
        "subtitle": "Missing metadata is a limited observation, not a conclusion about who made the image.",
        "image": "06-origin-evidence.png",
        "crop": (0, 600, 890, 1250),
        "blocks": [
            ("Metadata coverage", "The panel reports whether EXIF, IPTC, and XMP metadata were found. Missing metadata does not prove someone removed it."),
            ("Inspection receipt", "Open <b>Inspection reasons &amp; receipt</b> to read reason codes and the inspected image hash. <b>Inspect image again</b> runs and saves another inspection; earlier inspection records are preserved. Refresh reloads the current saved result."),
            ("This screenshot says Absent", "It means no Content Credentials manifest was found in the inspected image. It does not prove human authorship, prove AI use, or settle whether copying occurred. Treat the result as evidence only about available declarations and metadata."),
        ],
    },
    {
        "label": "6 · SHARE & EXPORT",
        "title": "Create a limited verification link",
        "subtitle": "Choose which facts to disclose and how long the link should remain active.",
        "image": "07-share-export.png",
        "crop": (0, 0, 890, 760),
        "blocks": [
            ("Choose the share scope", "Select any relevant items: <b>Registration status</b>, <b>Provenance status</b>, and/or <b>Rights preferences</b>. The recipient can read the selected minimized summary through the link."),
            ("Choose expiry and create", "Pick 1 hour, 1 day, 7 days, or 30 days, then choose <b>Create verification link</b>. Copy it and send it only to people who should see that summary."),
            ("Treat the link like a secret", "Anyone who has the link can access it until it expires or you revoke it. The link list is saved in this browser; revoke active links there when they are no longer needed."),
        ],
    },
    {
        "label": "6 · SHARE & EXPORT",
        "title": "Download preferences and check privacy",
        "subtitle": "Preference files are downloads; someone must publish them on the artist’s website.",
        "image": "07-share-export.png",
        "crop": (0, 620, 890, 1440),
        "blocks": [
            ("Available preference exports", "The screen offers Rights Passport JSON, AI preferences JSON, an <code>ai.txt</code> fragment, TDM policy JSON, and a readable rights statement. These files do not install themselves on a website. The artist or site operator must publish the relevant file at the correct location."),
            ("Privacy boundary", "The public verification link omits private contact details, uploaded images, and internal model outputs. A full authenticated export may include a licensing contact, so inspect it before sharing."),
            ("Limits", "An export or verification link does not prevent misuse. Signed C2PA authoring is not available in this screen."),
        ],
    },
]


def make_crop(source: Path, crop, target: Path) -> Path:
    if crop is None:
        return source
    with Image.open(source) as image:
        image.crop(crop).save(target)
    return target


def draw_paragraph(c, text: str, style, x: float, y: float, width: float) -> float:
    para = Paragraph(text, style)
    _, height = para.wrap(width, PAGE_H)
    para.drawOn(c, x, y - height)
    return y - height - style.spaceAfter


def draw_header(c, page_no: int, label: str, title: str, subtitle: str):
    c.setFillColor(BG)
    c.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
    c.setFillColor(colors.HexColor("#162749"))
    c.rect(0, PAGE_H - 5, PAGE_W, 5, fill=1, stroke=0)
    c.setFillColor(BLUE)
    c.setFont("GuideSans-Bold", 7.2)
    c.drawString(34, PAGE_H - 27, "CREATORPROOF  /  ARTIST PORTAL")
    c.setFillColor(MUTED)
    c.setFont("GuideSans-Bold", 7.3)
    c.drawRightString(PAGE_W - 34, PAGE_H - 27, label.upper())
    c.setFillColor(INK)
    c.setFont("GuideSans-Bold", 18)
    c.drawString(34, PAGE_H - 54, title)
    c.setFillColor(MUTED)
    c.setFont("GuideSans", 8.5)
    c.drawString(34, PAGE_H - 70, subtitle)
    c.setStrokeColor(PANEL_LINE)
    c.setLineWidth(0.6)
    c.line(34, PAGE_H - 80, PAGE_W - 34, PAGE_H - 80)
    c.setFillColor(MUTED)
    c.setFont("GuideSans", 7)
    c.drawString(34, 20, "Artwork Library walkthrough · Screenshots captured 10 October 2026")
    c.drawRightString(PAGE_W - 34, 20, f"{page_no:02d}")


def render_page(c, page_no: int, page, crop_dir: Path):
    draw_header(c, page_no, page["label"], page["title"], page["subtitle"])
    img_path = None
    if page.get("image"):
        source = IMAGE_DIR / page["image"]
        crop = page.get("crop")
        img_path = make_crop(source, crop, crop_dir / f"page-{page_no:02d}.png")

    panel_x, panel_y, panel_w, panel_h = 490, 42, PAGE_W - 524, PAGE_H - 140
    c.setFillColor(PANEL)
    c.setStrokeColor(PANEL_LINE)
    c.roundRect(panel_x, panel_y, panel_w, panel_h, 10, fill=1, stroke=1)

    if img_path:
        image_x, image_y, image_w, image_h = 34, 42, 442, PAGE_H - 140
        with Image.open(img_path) as im:
            iw, ih = im.size
        scale = min(image_w / iw, image_h / ih)
        draw_w, draw_h = iw * scale, ih * scale
        dx = image_x + (image_w - draw_w) / 2
        dy = image_y + (image_h - draw_h) / 2
        c.setFillColor(colors.HexColor("#0D1320"))
        c.setStrokeColor(PANEL_LINE)
        c.roundRect(image_x, image_y, image_w, image_h, 10, fill=1, stroke=1)
        c.saveState()
        path = c.beginPath()
        path.roundRect(image_x + 5, image_y + 5, image_w - 10, image_h - 10, 7)
        c.clipPath(path, stroke=0)
        c.drawImage(str(img_path), dx, dy, width=draw_w, height=draw_h, preserveAspectRatio=True, mask="auto")
        c.restoreState()

    x = panel_x + 16
    width = panel_w - 32
    y = PAGE_H - 98
    for heading, content in page["blocks"]:
        y = draw_paragraph(c, escape(heading), BLOCK_TITLE, x, y, width)
        y = draw_paragraph(c, content, BODY, x, y, width)
        if y < panel_y + 12:
            raise ValueError(f"Text overflow on PDF page {page_no}: {heading} (bottom={y:.1f})")
    c.showPage()


def render_final_pages(c, first_page: int):
    # A clean, full-width action checklist and limits page, easier to use while operating the app.
    page_no = first_page
    draw_header(
        c, page_no, "FIRST USE",
        "A safe, useful first-use sequence",
        "Follow these steps from registration through a candidate scan and human review.",
    )
    left_x, right_x, col_w = 36, 440, 365
    y_top = PAGE_H - 105
    boxes = [
        (left_x, y_top, col_w, "SET UP THE REFERENCE", [
            "<b>1.</b> Register the original image with a clear title and correct claimant.",
            "<b>2.</b> Open registration details and confirm the catalog. Keep <code>artist-library</code> if you want it in the default User scan.",
            "<b>3.</b> Open Permissions. Choose a starting preset only if it reflects the artist’s real intent; review every group and add accurate attribution, contact, and scope details. Save the policy version.",
            "<b>4.</b> Add known, real creation steps. Verify the history and export it if you need a portable record.",
        ]),
        (right_x, y_top, col_w, "INSPECT, SHARE, AND REVIEW", [
            "<b>5.</b> Check Origin evidence for signed creation declarations and metadata. Read absent or unavailable as “not found/checked,” not as proof of human origin.",
            "<b>6.</b> Share only the facts needed, or download a preference file. Publishing a downloaded file is a separate website task.",
            "<b>7.</b> In the User portal, submit a candidate and scan the same catalog. A flagged scan becomes available in Admin for human review.",
            "<b>8.</b> Compare the evidence and make a reasoned decision. A model score alone is not a legal finding.",
        ]),
        (left_x, 244, col_w, "WHAT THESE TOOLS DO NOT PROVE", [
            "A registration, artist-recorded claim, integrity hash, or similarity score does not by itself prove legal ownership or infringement.",
            "The Artwork library does not display candidate detections; those appear in the User and Admin workflows.",
            "A permission preference is not a contract and does not enforce itself across the web.",
        ]),
        (right_x, 244, col_w, "READ RESULTS WITH CARE", [
            "A no-match result covers only the catalog and sources actually checked; it cannot establish that an image is unused everywhere.",
            "Metadata inspection describes available embedded declarations. It cannot determine every tool used to create an image.",
            "Integrity status checks record consistency, not whether a human-authored event is truthful.",
        ]),
    ]
    for x, top, w, title, items in boxes:
        box_h = 220 if top > 300 else 178
        y = top - box_h
        c.setFillColor(PANEL)
        c.setStrokeColor(PANEL_LINE)
        c.roundRect(x, y, w, box_h, 10, fill=1, stroke=1)
        cursor = top - 20
        cursor = draw_paragraph(c, escape(title), BLOCK_TITLE, x + 15, cursor, w - 30)
        for item in items:
            cursor = draw_paragraph(c, bullet(item), SMALL, x + 15, cursor, w - 30)
            if cursor < y + 9:
                raise ValueError(f"Checklist text overflow on page {page_no}: {title}")
    c.showPage()

    page_no += 1
    draw_header(
        c, page_no, "REFERENCE",
        "Where to find the walkthrough details",
        "Use the matching page tab and numbered markers when following along in the Artist portal.",
    )
    references = [
        ("Library and registration", "Pages 1–3 · collection controls, Register artwork, record details, and catalog matching."),
        ("Permissions", "Pages 4–8 · quick choices, individual permission settings, scope, version history, and claims."),
        ("Creative process and provenance", "Pages 9–13 · Creation history fields, integrity checks, Content Credentials, and metadata."),
        ("Share and export", "Pages 14–15 · verification links, expiration, preference files, and privacy."),
        ("First-use checklist and boundaries", "Page 16 · an end-to-end operating sequence and the limits of each type of evidence."),
    ]
    y = PAGE_H - 111
    for heading, body in references:
        c.setFillColor(PANEL)
        c.setStrokeColor(PANEL_LINE)
        c.roundRect(70, y - 62, PAGE_W - 140, 52, 9, fill=1, stroke=1)
        y = draw_paragraph(c, escape(heading), BLOCK_TITLE, 88, y - 13, PAGE_W - 176)
        y = draw_paragraph(c, body, BODY, 88, y, PAGE_W - 176) - 10
    c.setFillColor(MUTED)
    c.setFont("GuideSans", 8)
    c.drawString(70, 58, "Source: docs/guides/ARTWORK_LIBRARY_WALKTHROUGH.md and the running local CreatorProof website.")
    c.showPage()


def main():
    if not GUIDE.exists():
        raise FileNotFoundError(GUIDE)
    missing = [p["image"] for p in PAGES if not (IMAGE_DIR / p["image"]).exists()]
    if missing:
        raise FileNotFoundError("Missing screenshot(s): " + ", ".join(missing))
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    pdf = canvas.Canvas(str(OUTPUT), pagesize=(PAGE_W, PAGE_H), pageCompression=1)
    pdf.setTitle("CreatorProof Artwork Library — Visual Walkthrough")
    pdf.setAuthor("CreatorProof")
    pdf.setSubject("Annotated step-by-step guide to the CreatorProof Artist Artwork Library")
    with TemporaryDirectory(prefix="creatorproof-artwork-pdf-") as temp:
        crop_dir = Path(temp)
        for page_no, page in enumerate(PAGES, start=1):
            render_page(pdf, page_no, page, crop_dir)
    render_final_pages(pdf, len(PAGES) + 1)
    pdf.save()
    print(f"Created {OUTPUT}")
    print(f"Pages: {len(PAGES) + 2}")


if __name__ == "__main__":
    main()
