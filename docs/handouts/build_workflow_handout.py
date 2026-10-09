"""Build the editable workflow guide and its print-ready PDF, without app changes."""

from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import Flowable, Paragraph, Table, TableStyle

ROOT = Path(__file__).resolve().parent
BASE = "CreatorProof_Final_Product_Workflow_Handout"
BLUE = colors.HexColor("#245EEA")
INK = colors.HexColor("#16243A")
MUTED = colors.HexColor("#53647A")
LINE = colors.HexColor("#DDE5F0")
PALE = colors.HexColor("#F2F6FF")
WIDTH, HEIGHT = A4
MARGIN = 43
CONTENT = WIDTH - 2 * MARGIN

for name, filename in [
    ("Guide", "DejaVuSans.ttf"),
    ("GuideBold", "DejaVuSans-Bold.ttf"),
]:
    pdfmetrics.registerFont(TTFont(name, f"/usr/share/fonts/truetype/dejavu/{filename}"))
pdfmetrics.registerFontFamily("Guide", normal="Guide", bold="GuideBold")

BODY = ParagraphStyle("Body", fontName="Guide", fontSize=10.2, leading=14.4, textColor=INK)
SMALL = ParagraphStyle("Small", parent=BODY, fontSize=9, leading=12.8, textColor=MUTED)
TITLE = ParagraphStyle("Title", parent=BODY, fontName="GuideBold", fontSize=26, leading=31)
SUBTITLE = ParagraphStyle("Subtitle", parent=BODY, fontSize=11, leading=16, textColor=MUTED)
H2 = ParagraphStyle("Heading", parent=BODY, fontName="GuideBold", fontSize=12, leading=16)
CELL = ParagraphStyle("Cell", parent=BODY, fontSize=9.3, leading=13)
CELL_HEAD = ParagraphStyle("CellHead", parent=CELL, fontName="GuideBold", textColor=BLUE)


def step(number, title, body, result=None):
    return {"type": "step", "number": number, "title": title, "body": body, "result": result}


def box(title, body):
    return {"type": "box", "title": title, "body": body}


def table(headers, rows, widths=None):
    return {"type": "table", "headers": headers, "rows": rows, "widths": widths}


def heading(title):
    return {"type": "heading", "text": title}


def para(text):
    return {"type": "paragraph", "text": text}


def link(title, url):
    return {"type": "link", "title": title, "url": url}


PAGES = [
    {
        "section": "START HERE",
        "title": "The whole journey, in one view",
        "intro": "CreatorProof helps artists record their work, say how it may be used, find supported reuse, and choose the next action with evidence.",
        "blocks": [
            box("How to read this handout", "This explains the final product experience in plain language. The Firewall API, partner enforcement and other planned services are described as their target workflow, not as already deployed features. Page 11 separates available capabilities from planned additions."),
            {"type": "overview"},
            table(["Who uses it?", "What they do"], [
                ["Artist", "Registers the original, sets preferences, records the creative process and helps resolve permission questions."],
                ["User / creative team", "Checks an image and its intended use before publishing."],
                ["Admin / reviewer", "Inspects flagged cases, checks permission, approves the action and keeps the record."],
                ["Partner platform (planned)", "Connects its upload or image-download flow to the Firewall API and applies the returned decision."],
            ], [0.31, 0.69]),
            heading("Three questions to keep separate"),
            para("<b>Was this artwork reused?</b> Picture comparison answers that. <b>Are there signs of AI involvement?</b> Origin checks answer that. <b>Is this use allowed?</b> Preferences, licenses and human review answer that. A copy can be licensed; AI involvement alone is not misuse."),
            para("<b>Useful words:</b> a reference is the registered original; a candidate is the image being checked; a license is permission with agreed terms; an API is a way for two applications to exchange requests automatically."),
        ],
    },
    {
        "section": "ARTIST · BUILD THE RECORD",
        "title": "Start with the artist's original",
        "intro": "The artist creates the reference that later images will be compared against. The final product account flow keeps each artist's private records separate.",
        "blocks": [
            step("1", "Upload and name the artwork", "Choose the reference image, check its preview, enter its title and the artist / claimant name, then register it. CreatorProof checks file safety, size and supported formats, and screens for available AI-origin evidence. A policy refusal keeps the form so the artist can correct it.", "A saved artwork ID and reference image, or an explained refusal / error."),
            step("2", "Create the picture's identification record", "Record an exact file fingerprint and a visual fingerprint. The first can confirm an identical file; the second helps find changed copies. Read existing Content Credentials when present. Registration records the artist's claim; it is not a government copyright registration or automatic proof of ownership."),
            step("3", "Set the artwork's rules", "Open Permissions / Rights Passport. Record choices about AI training, fine-tuning, AI editing, image-to-image use, style reference, derivative generation, search and likeness use. Choose allowed, denied, license required, needs review, unknown or not applicable. Add credit, licensing contact, fee and limits such as country, platform, model, channel or dates.", "A versioned permission card. New works start with unspecified permissions; saving an update preserves earlier versions."),
            step("4", "Record how the work was made", "In Creation history, add sketches, manual edits, AI-assisted steps, human selections, exports and supporting records. Say which tool was used and what the human decided. The system checks that the saved event chain has not been changed.", "A readable creative-process timeline, separate from the origin detector's assessment."),
            box("What happens next?", "The artist can export the permission card and creation history, inspect provenance, and share selected verification facts. The final product will connect these rights to protected previews, licensing requests and follow-up alerts as partner and artist services are completed."),
        ],
    },
    {
        "section": "USER + DISCOVERY · BRING IN A PICTURE",
        "title": "How an image reaches the checks",
        "intro": "An uploaded image, a connected-source discovery and a planned partner API submission all enter the same evidence-and-permission process.",
        "blocks": [
            heading("Route A · A user checks before publishing"),
            step("1", "Choose the picture and reference collection", "Upload the image or select a picture from an approved connected source. Choose the registered-artwork collection to compare against. A collection is simply the group of references this scan is allowed to search."),
            step("2", "Explain the intended use", "Say whether it is for an article, advertisement, sale, remix or AI-related use. Add relevant publication country, platform, audience and transformation details. Provide the public source URL if one exists. A private upload can be reviewed, but an external removal request needs the actual public location."),
            step("3", "Run the check and read the result", "CreatorProof checks the candidate, saves the evidence and shows the result. Completed flags are stored for Admin with available image comparisons, intended use, source URL, country declaration and detector details. Clean results do not need an Admin action."),
            heading("Route B · Monitoring discovers a picture"),
            step("1", "Select a source and search", "An operator chooses an approved connector, search terms and reference collection. Existing connectors include Unsplash, Pixabay and eBay; the supplied eBay setup uses sandbox listings, not the live production marketplace."),
            step("2", "Save new discoveries and compare", "Record the available image / preview, source page, discovery time and available listing or creator details. Keep previous history. Skip already recorded source IDs, then send new candidates through the same checks. Cross-source visual duplicate handling is a planned improvement."),
            box("Monitoring in the final product", "A server schedule will keep checking connected sources even when nobody has the Admin page open, and send artist alerts. Today the Admin monitor starts after 60 seconds and runs while that page remains open. Connected image-search APIs do not search the entire internet."),
            para("<b>Route C:</b> a partner submits an image automatically through the planned Firewall API. See page 6. Source access, attribution and permitted preview storage still follow the connected platform's terms."),
        ],
    },
    {
        "section": "DETECTION · WHAT HAPPENS INSIDE",
        "title": "Check the image in separate steps",
        "intro": "The system gathers evidence first. It does not treat a similar-looking picture, an AI score or a missing license as a complete legal conclusion.",
        "blocks": [
            step("1", "Check for an identical file", "SHA-256 compares exact file fingerprints. If the candidate and reference have the same fingerprint, the files have identical bytes."),
            step("2", "Find likely registered matches", "Visual fingerprints and Meta SSCD search the allowed reference collection. SSCD turns the picture into a visual ID so crops, resized images and other changes can become candidates for closer checking."),
            step("3", "Verify the matching picture details", "SIFT / ORB find shared small details. Alignment checks such as USAC / MAGSAC test whether those details line up after a crop or resize. Structural comparison tests the aligned area. Multiple checks support a transformed-copy finding; a retrieval ranking alone is not enough."),
            step("4", "Check AI-origin indicators separately", "Sightengine supplies an AI-image signal when configured and available. Local detectors can be used if the primary request fails. Signed declarations and visible AI labels provide other context. High AI signal does not prove this artist's work was used for training."),
            step("5", "Read provenance and optional resemblance", "C2PA / c2patool checks existing signed image history. A valid credential and a trusted signer are different facts. Optional CSD compares resemblance to a consenting creator profile; it is a review clue, not artist identity or proof of stolen style."),
            step("6", "Save findings and check the intended use", "Keep model / rule identities, measured values, source scope, failures and the image fingerprints. Compare the stated use with effective artist preferences, recorded claims, license terms and the organization's rules.", "An evidence record plus a publication-policy decision, ready for the User and Admin views."),
            box("If a tool cannot complete its check", "Keep any independent supported finding, explain the missing check and use review where necessary. A failed or unmeasured check is never silently shown as zero, safe or completed."),
        ],
    },
    {
        "section": "RESULTS · READ THE DECISION",
        "title": "Know what each result means",
        "intro": "The Evidence Matrix displays eight separate questions. Read the named measurement and finding, then the publication decision.",
        "blocks": [
            table(["Card", "What the reader learns"], [
                ["Visual reuse", "Exact copying or validated reuse of a registered work; copy evidence index where measured."],
                ["AI origin", "The recorded AI detector signal and the limits of its evidence."],
                ["Provenance", "Whether credentials exist, validate and have a trusted signer."],
                ["Creator resemblance", "Measured style / creator-profile resemblance, kept advisory."],
                ["Permissions", "Recorded authorizing licenses, conflicts and missing permission facts."],
                ["Publication policy", "PASS, REVIEW or BLOCK under the recorded organizational rules."],
                ["Source coverage", "Which registered references and sources were actually checked."],
                ["Record integrity", "Whether the saved evidence fingerprint verifies without changes."],
            ], [0.30, 0.70]),
            heading("The three action branches"),
            table(["Decision", "What happens after it"], [
                ["PASS · Allowed by policy", "Proceed with the declared use under the recorded rules. A licensed copy can pass. This is not a guarantee of rights beyond what was checked."],
                ["REVIEW · Hold for a person", "Keep the image pending. Admin checks missing facts, outside licenses, contradictions and source details."],
                ["BLOCK · Stop under policy", "Withhold the image inside CreatorProof or an integrated partner's flow. An external site's content is not automatically removed."],
            ], [0.31, 0.69]),
            box("How to explain a /100 rating", "It is the named model's index or output on a readable scale, not a percentage chance of copyright infringement. Copy, AI and style values are not averaged. A confirmed match with unknown permission remains a permission-review case."),
            para("<b>If no supported match is found:</b> say ‘No supported reuse found in the checked collection.’ Do not say the image is original everywhere. If the checks are incomplete, show what is missing and request review."),
        ],
    },
    {
        "section": "FINAL PRODUCT · FIREWALL API",
        "title": "Put the check inside a partner's app",
        "intro": "The planned Firewall API is CreatorProof's automatic connection to an upload, publication or image-use flow on another platform.",
        "blocks": [
            {"type": "api_flow"},
            step("1", "The platform connects once", "The partner enables CreatorProof on its server with a private credential and an allowed reference collection. Keys stay off public browser pages. Artists must authorize wider sharing of their references."),
            step("2", "A person uploads or requests use of an image", "Before publication, send the image or approved image reference, intended use and permission / license details. The user sees ‘Checking artwork permissions…’ in the planned interface."),
            step("3", "CreatorProof runs the same evidence checks", "Run page 4's checks and page 5's permission evaluation. Save the scan ID and result. Handle repeated requests consistently so one submission does not create several cases."),
            step("4", "Return a decision the platform can use", "Return PASS, REVIEW or BLOCK with reasons, matched artwork IDs, license conditions, evidence references and missing checks. A long scan first returns ‘Pending’ and a scan ID; the partner waits for completion."),
            step("5", "The platform applies the decision", "PASS continues with required terms such as credit. REVIEW holds publication and opens a case. BLOCK refuses this use with a reason. Service failure follows the agreed review / hold rule, never a false clearance."),
            step("6", "A human can resolve the hold", "A reviewer confirms a license, rejects publication or requests facts. The planned partner notification carries the recorded decision for this image and use. A changed image or use needs a fresh check."),
            box("What the API can control", "The partner enforces the response; CreatorProof cannot remotely control every website. Existing scan, rights and review APIs supply foundations. The complete partner Firewall integration is planned, not deployed."),
        ],
    },
    {
        "section": "FINAL PRODUCT · PROTECTED ACCESS",
        "title": "Make unwanted access harder",
        "intro": "The Firewall also protects originals hosted by CreatorProof or a cooperating partner. Picture checking and download protection are two parts of the same final-product design.",
        "blocks": [
            step("1", "Publish the preview; keep the original private", "The artist publishes a smaller viewing copy. The original sits in private storage. Public previews help people discover the work without giving everyone the full-quality source."),
            step("2", "Check a download request", "Before releasing the full file, check the requester, the artist's permissions, the exact artwork, requested use, current license, credit requirements, dates and scope. Unknown permission means ask / review, not automatic approval."),
            step("3", "Give approved access for a limited time", "For an authorized request, issue a short-lived download link. Log the request and the decision. A copied link eventually expires; new requests must pass the access checks again."),
            step("4", "Limit automated collecting", "The planned access gateway limits rapid bulk requests, detects suspicious patterns and can challenge or block them. It records which access rule was applied. These are software controls, not a single AI detector."),
            step("5", "Publish the artist's machine-readable preferences", "Export the AI-use choices in a form compatible tools can read, including an ai.txt fragment and supported text-and-data-mining signals. In the final integration, the reviewed declarations are installed on the website serving the art. Exporting a file alone does not publish or enforce it."),
            heading("If a requester needs a license"),
            para("The planned request screen asks who will use the art, for which purpose, where, for how long and under what payment / credit terms. The artist approves or declines. Save the agreed license and check those terms on future uses. Existing license records support checking; request negotiation and payment handling are planned product flows."),
            box("A rule card and a lock do different jobs", "‘Do not train’ expresses the artist's preference to cooperating systems. Access controls make full-file collection harder. Neither can stop every screenshot, retrieve copies already downloaded, control unrelated sites or prove whether a particular AI model trained on the work."),
            link("Reference: TDM preference signals (community specification)", "https://www.w3.org/community/reports/tdmrep/CG-FINAL-tdmrep-20240510/"),
        ],
    },
    {
        "section": "ADMIN · FROM A FLAG TO ACTION",
        "title": "A person decides what happens next",
        "intro": "A stored flag is an investigation starting point. An image match, missing recorded license or AI signal is not an automatic takedown.",
        "blocks": [
            step("1", "Open the case and compare the images", "Use Review inbox or Stored cases. Compare the original and observed image. Read the source, dates, stated use, country declaration and measurements. Supported regions / alignment explain the match."),
            step("2", "Check whether the use is actually a problem", "Verify claimant authority, licenses, preferences, publication context and relevant exceptions. Ask for missing facts. A declared country or listing location does not prove the alleged copier's residence or determine applicable law."),
            step("3", "Choose the next action", "Approve publication, reject it under policy, request a license or record that further review is needed. Save the decision. Artist alerts and managed follow-up messages are planned."),
            step("4", "Prepare a request only when justified", "Confirm claimant contact / authority, protected-work details, exact public URLs, facts, recipient and procedure. The AI assistant drafts from those supplied facts, without inventing ownership, residence or evidence. Save the draft and generation record."),
            box("Draft status", "A saved notice is a reviewed draft, not proof of infringement or proof that the platform received it. The operator remains responsible for checking the facts and choosing whether to submit."),
        ],
    },
    {
        "section": "ADMIN · PREPARE + SUBMIT",
        "title": "Use the right reporting process",
        "intro": "The operator selects the route that fits the recipient and location. The notice assistant can prepare text; a person checks it and decides whether to submit.",
        "blocks": [
            table(["Procedure", "How to explain it"], [
                ["US · DMCA", "Prepare the work / disputed-location identifiers, claimant contact, required statements and authorized signature. Submit to the service's designated agent or official reporting form. [1]"],
                ["EU · DSA", "Use the platform's notice-and-action channel, with the exact location and a reasoned explanation of alleged illegality under applicable law. DSA is a reporting process, not a replacement copyright law. [2]"],
                ["Other locations", "UK, Canada, Australia and international draft families are available. The operator checks local procedure and platform requirements; Canada may involve notice-and-notice. There is no single universal takedown format."],
            ], [0.24, 0.76]),
            step("5", "Review, approve and submit", "Check every claim, then submit through the proper channel. Current email handoff opens a draft; it does not confirm sending. The planned delivery service will require explicit approval and keep delivery receipts."),
            para("<b>After submission:</b> track reply, removal, permission, appeal / counter-notice or closure. Sending a request does not guarantee removal; contested cases remain reviewable."),
            link("[1] US Copyright Office · Section 512 notices", "https://copyright.gov/512/index.html"),
            link("[2] European Commission · DSA notice and action", "https://digital-strategy.ec.europa.eu/en/policies/dsa-notice-and-action-mechanism"),
        ],
    },
    {
        "section": "RECORDS · PRIVACY + PRODUCT STATUS",
        "title": "Keep useful proof, not everything public",
        "intro": "The record lets another reviewer understand what was checked, what was unknown and why a person took a particular action.",
        "blocks": [
            step("1", "Save the case and its history", "Keep the source and discovery time, reference and candidate fingerprints, available image comparison, detector results, permission snapshot, model identities, draft and human decision. A new assessment is saved separately; earlier evidence is preserved."),
            step("2", "Separate temporary files from stored cases", "Temporary candidate uploads expire under the configured retention policy. An explicitly archived comparison keeps its own copies until removed or the registered work is deleted. Repeated discoveries do not erase old cases. Deleted bytes cannot be recovered from a fingerprint."),
            step("3", "Share only selected verification facts", "Create a scoped verification link with an expiry, and revoke it when needed. The public view excludes private images, contacts and internal provider data. A verified hash shows the record has not changed; it does not prove ownership or a detector's correctness. Optional blockchain anchoring commits a hash only, when configured and confirmed."),
        ],
    },
    {
        "section": "PRODUCT STATUS · AVAILABLE + PLANNED",
        "title": "Be clear about what works today",
        "intro": "Use this distinction when explaining the prototype. Some working building blocks are already present; the complete partner-connected product still needs implementation.",
        "blocks": [
            heading("Know which features are available and which are planned"),
            table(["Available project capabilities", "Planned final-product additions"], [
                ["Artwork registration, reference storage and permission versions", "Finished end-user account / artist onboarding flows and protected-publication experience"],
                ["Creation ledger, provenance reads and safe verification links", "Integrated preview/original gateway, bot controls and expiring licensed downloads"],
                ["Evidence checks, measured cards and scan / rights APIs", "Complete partner Firewall API package, partner enforcement and result notifications"],
                ["Unsplash / Pixabay / eBay connector; supplied eBay sandbox setup", "Production eBay access as approved; more authorized source integrations"],
                ["Admin-page monitoring and saved discovery history", "Always-on server scheduling and artist alert delivery"],
                ["Review decisions, saved comparisons, licenses and notice drafts", "Artist licensing-request negotiation / payment, approved delivery and outcome / appeal tracking"],
            ], [0.5, 0.5]),
            box("The teammate's safe wording", "Say ‘The final product will put this check into a partner's publishing flow.’ Do not say the unimplemented Firewall integration is already deployed. Existing APIs are foundations, and saved comparisons can be opened now without running the process again."),
        ],
    },
    {
        "section": "TEAMMATE · WORKED EXAMPLE",
        "title": "Explain the whole workflow with one story",
        "intro": "Use this example to connect registration, the Firewall, detection and human action.",
        "blocks": [
            box("Example · Maya's painting", "Maya registers a painting, records her creation steps and sets a preference that ads require a license. In the final product, a partner marketplace receives a cropped version on a product listing. Its Firewall connection holds publication while CreatorProof checks it. The copy checks support reuse, but no matching license is on file, so Admin reviews rather than claiming infringement automatically. Maya confirms the permission facts. The reviewer can request a license or reject that use. If the image is already public elsewhere and the facts justify action, a person approves the appropriate notice. The decision and evidence stay in the case record."),
            para("<b>Two different endings:</b> if a valid license covers this use, record it and apply the permitted-use decision. If only style or AI resemblance is found without validated artwork reuse, investigate that signal; do not draft a copying notice from that alone."),
            box("The short explanation to say aloud", "‘Artists register the original and record their rules. CreatorProof checks submitted or discovered images against those references, checks the intended use, and keeps clear evidence. In the final product, partner apps will use the Firewall API to allow, hold or block a use before publication. A human reviews flagged cases and approves any licensing or removal action.’"),
        ],
    },
    {
        "section": "TEAMMATE · QUICK REFERENCE",
        "title": "Find a saved case and decode the terms",
        "intro": "Use the stored comparisons for a quick walkthrough. The glossary explains the technical names in plain language.",
        "blocks": [
            table(["Name you may hear", "Plain-language job"], [
                ["SHA-256 / perceptual hash", "Exact-file ID / quick visual fingerprint."],
                ["SSCD / SIFT / ORB / MAGSAC", "Find likely copies, then test matching details and alignment."],
                ["Sightengine / local fallbacks", "Check AI-origin indicators, separately from copying."],
                ["CSD / C2PA", "Advisory resemblance / checks on existing signed image history."],
                ["Rights Passport / license", "Artist's preference card / recorded agreed permission."],
                ["Evidence Matrix / ledger", "Eight questions about a scan / the artwork's creation timeline."],
                ["Firewall API / connector", "Partner gate before use / source that supplies discoverable images."],
                ["Next.js / FastAPI / storage", "The screens / backend coordinator / private files and database records."],
            ], [0.39, 0.61]),
            heading("Use the saved comparisons during the pitch"),
            para("Open <b>Admin → Stored cases</b>. Select full-image republication, cropped publication or the AI sky edit. Show both pictures, open Detailed evidence, then Prepare notice. Images, measurements and drafts are saved; reopening does not run inference. The collection uses project-owned comparison images and real scans, not established third-party infringement cases. The API and storage must remain running."),
        ],
    },
]


def p(text, style=BODY):
    return Paragraph(text, style)


class Diagram(Flowable):
    def __init__(self, mode):
        super().__init__()
        self.mode = mode
        self.width = CONTENT
        self.height = 129 if mode == "overview" else 67

    def draw(self):
        c = self.canv
        if self.mode == "overview":
            gap, w, h = 19, (CONTENT - 38) / 3, 51
            labels = [("1 · Register", "Artist's reference"), ("2 · Set rules", "Preferences + licenses"), ("3 · Protect", "Planned Firewall"), ("6 · Save", "Evidence + decision"), ("5 · Decide", "Policy + human action"), ("4 · Check", "Submitted / found image")]
            positions = [(0, 75), (w+gap, 75), (2*(w+gap), 75), (0, 5), (w+gap, 5), (2*(w+gap), 5)]
            arrows = [(w, 100, w+gap, 100), (2*w+gap,100,2*(w+gap),100), (2*(w+gap)+w/2,75,2*(w+gap)+w/2,56), (2*(w+gap),30,2*w+gap,30), (w+gap,30,w,30)]
        else:
            gap, w, h = 13, (CONTENT-39)/4, 54
            labels = [("Partner app", "Submit image + use"), ("CreatorProof", "Check + save"), ("Policy result", "PASS / REVIEW / BLOCK"), ("Partner app", "Apply decision")]
            positions = [(i*(w+gap), 8) for i in range(4)]
            arrows = [(i*(w+gap)+w,35,(i+1)*(w+gap),35) for i in range(3)]
        for (title, body), (x, y) in zip(labels, positions):
            c.setFillColor(PALE); c.setStrokeColor(LINE); c.roundRect(x,y,w,h,9,fill=1,stroke=1)
            c.setFillColor(BLUE); c.setFont("GuideBold", 9.1); c.drawCentredString(x+w/2,y+h-19,title)
            c.setFillColor(MUTED); c.setFont("Guide",7.8); c.drawCentredString(x+w/2,y+14,body)
        for x1,y1,x2,y2 in arrows:
            c.setStrokeColor(BLUE); c.setLineWidth(1); c.line(x1+2 if x2>x1 else x1,y1,x2-2 if x2>x1 else x2,y2)
            if y2<y1: c.line(x2,y2,x2-3,y2+4);c.line(x2,y2,x2+3,y2+4)
            elif x2>x1: c.line(x2-2,y2,x2-6,y2+3);c.line(x2-2,y2,x2-6,y2-3)
            else: c.line(x2,y2,x2+4,y2+3);c.line(x2,y2,x2+4,y2-3)


def rounded_box(title, body):
    t=Table([[p(escape(title),H2)],[p(body,SMALL)]],colWidths=[CONTENT])
    t.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),PALE),("BOX",(0,0),(-1,-1),.5,LINE),("LEFTPADDING",(0,0),(-1,-1),13),("RIGHTPADDING",(0,0),(-1,-1),13),("TOPPADDING",(0,0),(-1,0),11),("BOTTOMPADDING",(0,0),(-1,0),5),("TOPPADDING",(0,1),(-1,-1),0),("BOTTOMPADDING",(0,1),(-1,-1),11)]))
    return t


def render_block(block):
    kind=block["type"]
    if kind=="step":
        right=[p(escape(block["title"]),H2), p(block["body"],BODY)]
        if block["result"]:right.append(p("<b>Result:</b> "+block["result"],SMALL))
        number=p(f'<font color="#245EEA"><b>{block["number"]}</b></font>',H2)
        t=Table([[number,right]],colWidths=[29,CONTENT-29])
        t.setStyle(TableStyle([("VALIGN",(0,0),(-1,-1),"TOP"),("LEFTPADDING",(0,0),(-1,-1),0),("RIGHTPADDING",(0,0),(-1,-1),0),("TOPPADDING",(0,0),(-1,-1),0),("BOTTOMPADDING",(0,0),(-1,-1),0)]))
        return t,6
    if kind=="box":return rounded_box(block["title"],block["body"]),11
    if kind=="heading":return p(escape(block["text"]),H2),9
    if kind=="paragraph":return p(block["text"]),8
    if kind in {"overview","api_flow"}:return Diagram(kind),14
    if kind=="link":return p(f'<link href="{escape(block["url"])}" color="#245EEA">{escape(block["title"])}</link>',SMALL),4
    if kind=="table":
        data=[[p(escape(x),CELL_HEAD) for x in block["headers"]]]+[[p(escape(x),CELL) for x in row] for row in block["rows"]]
        widths=block["widths"] or [1/len(block["headers"])]*len(block["headers"])
        t=Table(data,colWidths=[CONTENT*x for x in widths])
        t.setStyle(TableStyle([("VALIGN",(0,0),(-1,-1),"TOP"),("BACKGROUND",(0,0),(-1,0),PALE),("LINEBELOW",(0,0),(-1,0),.6,LINE),("LINEBELOW",(0,1),(-1,-1),.4,LINE),("LEFTPADDING",(0,0),(-1,-1),9),("RIGHTPADDING",(0,0),(-1,-1),9),("TOPPADDING",(0,0),(-1,-1),6),("BOTTOMPADDING",(0,0),(-1,-1),6)]))
        return t,14
    raise ValueError(kind)


def plain(text):
    return text.replace("<b>","**").replace("</b>","**")


def markdown():
    chunks=["# CreatorProof · Final Product Workflow Handout", "Updated 9 October 2026 · Plain-language teammate guide", ""]
    for i,page in enumerate(PAGES,1):
        chunks += [f"## {i}. {page['title']}",f"*{page['section']}*",page['intro'],""]
        for b in page["blocks"]:
            kind=b["type"]
            if kind=="step":chunks += [f"### Step {b['number']} · {b['title']}",plain(b["body"])]+(["**Result:** "+plain(b["result"])] if b["result"] else [])
            elif kind=="box":chunks += [f"### {b['title']}",plain(b["body"])]
            elif kind=="heading":chunks += [f"### {b['text']}"]
            elif kind=="paragraph":chunks += [plain(b["text"])]
            elif kind=="table":chunks += ["| "+" | ".join(b["headers"])+" |","| "+" | ".join(["---"]*len(b["headers"]))+" |"]+["| "+" | ".join(row)+" |" for row in b["rows"]]
            elif kind=="overview":chunks += ["Register → Set rules → Protect → Check → Decide → Save"]
            elif kind=="api_flow":chunks += ["Partner submits image + use → CreatorProof checks + saves → PASS / REVIEW / BLOCK → Partner applies the decision"]
            elif kind=="link":chunks += [f"[{b['title']}]({b['url']})"]
            chunks += [""]
    (ROOT/(BASE+".md")).write_text("\n\n".join(chunks)+"\n")


def build():
    out=ROOT/(BASE+".pdf")
    c=canvas.Canvas(str(out),pagesize=A4,pageCompression=1)
    c.setTitle("CreatorProof · Final Product Workflow Handout")
    c.setAuthor("CreatorProof")
    c.setSubject("Plain-language workflow; current capabilities and planned Firewall API integration")
    measures=[]
    for index,page in enumerate(PAGES,1):
        c.setFillColor(BLUE);c.roundRect(MARGIN,HEIGHT-44,7,7,2,fill=1,stroke=0)
        c.setFont("GuideBold",9.2);c.drawString(MARGIN+15,HEIGHT-44,"CREATORPROOF")
        c.setFillColor(MUTED);c.setFont("Guide",7.8);c.drawRightString(WIDTH-MARGIN,HEIGHT-44,"FINAL PRODUCT WORKFLOW · 9 OCT 2026")
        c.setStrokeColor(LINE);c.line(MARGIN,HEIGHT-56,WIDTH-MARGIN,HEIGHT-56)
        y=HEIGHT-79
        c.setFillColor(BLUE);c.setFont("GuideBold",8.2);c.drawString(MARGIN,y,page["section"])
        y-=13
        for flow,gap in [(p(escape(page["title"]),TITLE),11),(p(page["intro"],SUBTITLE),20)]+[render_block(b) for b in page["blocks"]]:
            _,height=flow.wrap(CONTENT,HEIGHT)
            if y-height<55:raise RuntimeError(f"Page {index} overflows by {55-(y-height):.1f}pt")
            flow.drawOn(c,MARGIN,y-height);y-=height+gap
        measures.append({"page":index,"remaining_points":round(y-43,1)})
        c.setStrokeColor(LINE);c.line(MARGIN,40,WIDTH-MARGIN,40)
        c.setFillColor(MUTED);c.setFont("Guide",7.4);c.drawString(MARGIN,26,"Final-product design · Available / planned status: page 11")
        c.drawRightString(WIDTH-MARGIN,26,f"{index} / {len(PAGES)}")
        c.showPage()
    c.save()
    markdown()
    print({"pdf":str(out),"pages":len(PAGES),"layout":measures})


if __name__=="__main__":build()
