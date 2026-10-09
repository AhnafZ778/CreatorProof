# CreatorProof · Final Product Workflow Handout

Updated 9 October 2026 · Plain-language teammate guide



## 1. The whole journey, in one view

*START HERE*

CreatorProof helps artists record their work, say how it may be used, find supported reuse, and choose the next action with evidence.



### How to read this handout

This explains the final product experience in plain language. The Firewall API, partner enforcement and other planned services are described as their target workflow, not as already deployed features. Page 11 separates available capabilities from planned additions.



Register → Set rules → Protect → Check → Decide → Save



| Who uses it? | What they do |

| --- | --- |

| Artist | Registers the original, sets preferences, records the creative process and helps resolve permission questions. |

| User / creative team | Checks an image and its intended use before publishing. |

| Admin / reviewer | Inspects flagged cases, checks permission, approves the action and keeps the record. |

| Partner platform (planned) | Connects its upload or image-download flow to the Firewall API and applies the returned decision. |



### Three questions to keep separate



**Was this artwork reused?** Picture comparison answers that. **Are there signs of AI involvement?** Origin checks answer that. **Is this use allowed?** Preferences, licenses and human review answer that. A copy can be licensed; AI involvement alone is not misuse.



**Useful words:** a reference is the registered original; a candidate is the image being checked; a license is permission with agreed terms; an API is a way for two applications to exchange requests automatically.



## 2. Start with the artist's original

*ARTIST · BUILD THE RECORD*

The artist creates the reference that later images will be compared against. The final product account flow keeps each artist's private records separate.



### Step 1 · Upload and name the artwork

Choose the reference image, check its preview, enter its title and the artist / claimant name, then register it. CreatorProof checks file safety, size and supported formats, and screens for available AI-origin evidence. A policy refusal keeps the form so the artist can correct it.

**Result:** A saved artwork ID and reference image, or an explained refusal / error.



### Step 2 · Create the picture's identification record

Record an exact file fingerprint and a visual fingerprint. The first can confirm an identical file; the second helps find changed copies. Read existing Content Credentials when present. Registration records the artist's claim; it is not a government copyright registration or automatic proof of ownership.



### Step 3 · Set the artwork's rules

Open Permissions / Rights Passport. Record choices about AI training, fine-tuning, AI editing, image-to-image use, style reference, derivative generation, search and likeness use. Choose allowed, denied, license required, needs review, unknown or not applicable. Add credit, licensing contact, fee and limits such as country, platform, model, channel or dates.

**Result:** A versioned permission card. New works start with unspecified permissions; saving an update preserves earlier versions.



### Step 4 · Record how the work was made

In Creation history, add sketches, manual edits, AI-assisted steps, human selections, exports and supporting records. Say which tool was used and what the human decided. The system checks that the saved event chain has not been changed.

**Result:** A readable creative-process timeline, separate from the origin detector's assessment.



### What happens next?

The artist can export the permission card and creation history, inspect provenance, and share selected verification facts. The final product will connect these rights to protected previews, licensing requests and follow-up alerts as partner and artist services are completed.



## 3. How an image reaches the checks

*USER + DISCOVERY · BRING IN A PICTURE*

An uploaded image, a connected-source discovery and a planned partner API submission all enter the same evidence-and-permission process.



### Route A · A user checks before publishing



### Step 1 · Choose the picture and reference collection

Upload the image or select a picture from an approved connected source. Choose the registered-artwork collection to compare against. A collection is simply the group of references this scan is allowed to search.



### Step 2 · Explain the intended use

Say whether it is for an article, advertisement, sale, remix or AI-related use. Add relevant publication country, platform, audience and transformation details. Provide the public source URL if one exists. A private upload can be reviewed, but an external removal request needs the actual public location.



### Step 3 · Run the check and read the result

CreatorProof checks the candidate, saves the evidence and shows the result. Completed flags are stored for Admin with available image comparisons, intended use, source URL, country declaration and detector details. Clean results do not need an Admin action.



### Route B · Monitoring discovers a picture



### Step 1 · Select a source and search

An operator chooses an approved connector, search terms and reference collection. Existing connectors include Unsplash, Pixabay and eBay; the supplied eBay setup uses sandbox listings, not the live production marketplace.



### Step 2 · Save new discoveries and compare

Record the available image / preview, source page, discovery time and available listing or creator details. Keep previous history. Skip already recorded source IDs, then send new candidates through the same checks. Cross-source visual duplicate handling is a planned improvement.



### Monitoring in the final product

A server schedule will keep checking connected sources even when nobody has the Admin page open, and send artist alerts. Today the Admin monitor starts after 60 seconds and runs while that page remains open. Connected image-search APIs do not search the entire internet.



**Route C:** a partner submits an image automatically through the planned Firewall API. See page 6. Source access, attribution and permitted preview storage still follow the connected platform's terms.



## 4. Check the image in separate steps

*DETECTION · WHAT HAPPENS INSIDE*

The system gathers evidence first. It does not treat a similar-looking picture, an AI score or a missing license as a complete legal conclusion.



### Step 1 · Check for an identical file

SHA-256 compares exact file fingerprints. If the candidate and reference have the same fingerprint, the files have identical bytes.



### Step 2 · Find likely registered matches

Visual fingerprints and Meta SSCD search the allowed reference collection. SSCD turns the picture into a visual ID so crops, resized images and other changes can become candidates for closer checking.



### Step 3 · Verify the matching picture details

SIFT / ORB find shared small details. Alignment checks such as USAC / MAGSAC test whether those details line up after a crop or resize. Structural comparison tests the aligned area. Multiple checks support a transformed-copy finding; a retrieval ranking alone is not enough.



### Step 4 · Check AI-origin indicators separately

Sightengine supplies an AI-image signal when configured and available. Local detectors can be used if the primary request fails. Signed declarations and visible AI labels provide other context. High AI signal does not prove this artist's work was used for training.



### Step 5 · Read provenance and optional resemblance

C2PA / c2patool checks existing signed image history. A valid credential and a trusted signer are different facts. Optional CSD compares resemblance to a consenting creator profile; it is a review clue, not artist identity or proof of stolen style.



### Step 6 · Save findings and check the intended use

Keep model / rule identities, measured values, source scope, failures and the image fingerprints. Compare the stated use with effective artist preferences, recorded claims, license terms and the organization's rules.

**Result:** An evidence record plus a publication-policy decision, ready for the User and Admin views.



### If a tool cannot complete its check

Keep any independent supported finding, explain the missing check and use review where necessary. A failed or unmeasured check is never silently shown as zero, safe or completed.



## 5. Know what each result means

*RESULTS · READ THE DECISION*

The Evidence Matrix displays eight separate questions. Read the named measurement and finding, then the publication decision.



| Card | What the reader learns |

| --- | --- |

| Visual reuse | Exact copying or validated reuse of a registered work; copy evidence index where measured. |

| AI origin | The recorded AI detector signal and the limits of its evidence. |

| Provenance | Whether credentials exist, validate and have a trusted signer. |

| Creator resemblance | Measured style / creator-profile resemblance, kept advisory. |

| Permissions | Recorded authorizing licenses, conflicts and missing permission facts. |

| Publication policy | PASS, REVIEW or BLOCK under the recorded organizational rules. |

| Source coverage | Which registered references and sources were actually checked. |

| Record integrity | Whether the saved evidence fingerprint verifies without changes. |



### The three action branches



| Decision | What happens after it |

| --- | --- |

| PASS · Allowed by policy | Proceed with the declared use under the recorded rules. A licensed copy can pass. This is not a guarantee of rights beyond what was checked. |

| REVIEW · Hold for a person | Keep the image pending. Admin checks missing facts, outside licenses, contradictions and source details. |

| BLOCK · Stop under policy | Withhold the image inside CreatorProof or an integrated partner's flow. An external site's content is not automatically removed. |



### How to explain a /100 rating

It is the named model's index or output on a readable scale, not a percentage chance of copyright infringement. Copy, AI and style values are not averaged. A confirmed match with unknown permission remains a permission-review case.



**If no supported match is found:** say ‘No supported reuse found in the checked collection.’ Do not say the image is original everywhere. If the checks are incomplete, show what is missing and request review.



## 6. Put the check inside a partner's app

*FINAL PRODUCT · FIREWALL API*

The planned Firewall API is CreatorProof's automatic connection to an upload, publication or image-use flow on another platform.



Partner submits image + use → CreatorProof checks + saves → PASS / REVIEW / BLOCK → Partner applies the decision



### Step 1 · The platform connects once

The partner enables CreatorProof on its server with a private credential and an allowed reference collection. Keys stay off public browser pages. Artists must authorize wider sharing of their references.



### Step 2 · A person uploads or requests use of an image

Before publication, send the image or approved image reference, intended use and permission / license details. The user sees ‘Checking artwork permissions…’ in the planned interface.



### Step 3 · CreatorProof runs the same evidence checks

Run page 4's checks and page 5's permission evaluation. Save the scan ID and result. Handle repeated requests consistently so one submission does not create several cases.



### Step 4 · Return a decision the platform can use

Return PASS, REVIEW or BLOCK with reasons, matched artwork IDs, license conditions, evidence references and missing checks. A long scan first returns ‘Pending’ and a scan ID; the partner waits for completion.



### Step 5 · The platform applies the decision

PASS continues with required terms such as credit. REVIEW holds publication and opens a case. BLOCK refuses this use with a reason. Service failure follows the agreed review / hold rule, never a false clearance.



### Step 6 · A human can resolve the hold

A reviewer confirms a license, rejects publication or requests facts. The planned partner notification carries the recorded decision for this image and use. A changed image or use needs a fresh check.



### What the API can control

The partner enforces the response; CreatorProof cannot remotely control every website. Existing scan, rights and review APIs supply foundations. The complete partner Firewall integration is planned, not deployed.



## 7. Make unwanted access harder

*FINAL PRODUCT · PROTECTED ACCESS*

The Firewall also protects originals hosted by CreatorProof or a cooperating partner. Picture checking and download protection are two parts of the same final-product design.



### Step 1 · Publish the preview; keep the original private

The artist publishes a smaller viewing copy. The original sits in private storage. Public previews help people discover the work without giving everyone the full-quality source.



### Step 2 · Check a download request

Before releasing the full file, check the requester, the artist's permissions, the exact artwork, requested use, current license, credit requirements, dates and scope. Unknown permission means ask / review, not automatic approval.



### Step 3 · Give approved access for a limited time

For an authorized request, issue a short-lived download link. Log the request and the decision. A copied link eventually expires; new requests must pass the access checks again.



### Step 4 · Limit automated collecting

The planned access gateway limits rapid bulk requests, detects suspicious patterns and can challenge or block them. It records which access rule was applied. These are software controls, not a single AI detector.



### Step 5 · Publish the artist's machine-readable preferences

Export the AI-use choices in a form compatible tools can read, including an ai.txt fragment and supported text-and-data-mining signals. In the final integration, the reviewed declarations are installed on the website serving the art. Exporting a file alone does not publish or enforce it.



### If a requester needs a license



The planned request screen asks who will use the art, for which purpose, where, for how long and under what payment / credit terms. The artist approves or declines. Save the agreed license and check those terms on future uses. Existing license records support checking; request negotiation and payment handling are planned product flows.



### A rule card and a lock do different jobs

‘Do not train’ expresses the artist's preference to cooperating systems. Access controls make full-file collection harder. Neither can stop every screenshot, retrieve copies already downloaded, control unrelated sites or prove whether a particular AI model trained on the work.



[Reference: TDM preference signals (community specification)](https://www.w3.org/community/reports/tdmrep/CG-FINAL-tdmrep-20240510/)



## 8. A person decides what happens next

*ADMIN · FROM A FLAG TO ACTION*

A stored flag is an investigation starting point. An image match, missing recorded license or AI signal is not an automatic takedown.



### Step 1 · Open the case and compare the images

Use Review inbox or Stored cases. Compare the original and observed image. Read the source, dates, stated use, country declaration and measurements. Supported regions / alignment explain the match.



### Step 2 · Check whether the use is actually a problem

Verify claimant authority, licenses, preferences, publication context and relevant exceptions. Ask for missing facts. A declared country or listing location does not prove the alleged copier's residence or determine applicable law.



### Step 3 · Choose the next action

Approve publication, reject it under policy, request a license or record that further review is needed. Save the decision. Artist alerts and managed follow-up messages are planned.



### Step 4 · Prepare a request only when justified

Confirm claimant contact / authority, protected-work details, exact public URLs, facts, recipient and procedure. The AI assistant drafts from those supplied facts, without inventing ownership, residence or evidence. Save the draft and generation record.



### Draft status

A saved notice is a reviewed draft, not proof of infringement or proof that the platform received it. The operator remains responsible for checking the facts and choosing whether to submit.



## 9. Use the right reporting process

*ADMIN · PREPARE + SUBMIT*

The operator selects the route that fits the recipient and location. The notice assistant can prepare text; a person checks it and decides whether to submit.



| Procedure | How to explain it |

| --- | --- |

| US · DMCA | Prepare the work / disputed-location identifiers, claimant contact, required statements and authorized signature. Submit to the service's designated agent or official reporting form. [1] |

| EU · DSA | Use the platform's notice-and-action channel, with the exact location and a reasoned explanation of alleged illegality under applicable law. DSA is a reporting process, not a replacement copyright law. [2] |

| Other locations | UK, Canada, Australia and international draft families are available. The operator checks local procedure and platform requirements; Canada may involve notice-and-notice. There is no single universal takedown format. |



### Step 5 · Review, approve and submit

Check every claim, then submit through the proper channel. Current email handoff opens a draft; it does not confirm sending. The planned delivery service will require explicit approval and keep delivery receipts.



**After submission:** track reply, removal, permission, appeal / counter-notice or closure. Sending a request does not guarantee removal; contested cases remain reviewable.



[[1] US Copyright Office · Section 512 notices](https://copyright.gov/512/index.html)



[[2] European Commission · DSA notice and action](https://digital-strategy.ec.europa.eu/en/policies/dsa-notice-and-action-mechanism)



## 10. Keep useful proof, not everything public

*RECORDS · PRIVACY + PRODUCT STATUS*

The record lets another reviewer understand what was checked, what was unknown and why a person took a particular action.



### Step 1 · Save the case and its history

Keep the source and discovery time, reference and candidate fingerprints, available image comparison, detector results, permission snapshot, model identities, draft and human decision. A new assessment is saved separately; earlier evidence is preserved.



### Step 2 · Separate temporary files from stored cases

Temporary candidate uploads expire under the configured retention policy. An explicitly archived comparison keeps its own copies until removed or the registered work is deleted. Repeated discoveries do not erase old cases. Deleted bytes cannot be recovered from a fingerprint.



### Step 3 · Share only selected verification facts

Create a scoped verification link with an expiry, and revoke it when needed. The public view excludes private images, contacts and internal provider data. A verified hash shows the record has not changed; it does not prove ownership or a detector's correctness. Optional blockchain anchoring commits a hash only, when configured and confirmed.



## 11. Be clear about what works today

*PRODUCT STATUS · AVAILABLE + PLANNED*

Use this distinction when explaining the prototype. Some working building blocks are already present; the complete partner-connected product still needs implementation.



### Know which features are available and which are planned



| Available project capabilities | Planned final-product additions |

| --- | --- |

| Artwork registration, reference storage and permission versions | Finished end-user account / artist onboarding flows and protected-publication experience |

| Creation ledger, provenance reads and safe verification links | Integrated preview/original gateway, bot controls and expiring licensed downloads |

| Evidence checks, measured cards and scan / rights APIs | Complete partner Firewall API package, partner enforcement and result notifications |

| Unsplash / Pixabay / eBay connector; supplied eBay sandbox setup | Production eBay access as approved; more authorized source integrations |

| Admin-page monitoring and saved discovery history | Always-on server scheduling and artist alert delivery |

| Review decisions, saved comparisons, licenses and notice drafts | Artist licensing-request negotiation / payment, approved delivery and outcome / appeal tracking |



### The teammate's safe wording

Say ‘The final product will put this check into a partner's publishing flow.’ Do not say the unimplemented Firewall integration is already deployed. Existing APIs are foundations, and saved comparisons can be opened now without running the process again.



## 12. Explain the whole workflow with one story

*TEAMMATE · WORKED EXAMPLE*

Use this example to connect registration, the Firewall, detection and human action.



### Example · Maya's painting

Maya registers a painting, records her creation steps and sets a preference that ads require a license. In the final product, a partner marketplace receives a cropped version on a product listing. Its Firewall connection holds publication while CreatorProof checks it. The copy checks support reuse, but no matching license is on file, so Admin reviews rather than claiming infringement automatically. Maya confirms the permission facts. The reviewer can request a license or reject that use. If the image is already public elsewhere and the facts justify action, a person approves the appropriate notice. The decision and evidence stay in the case record.



**Two different endings:** if a valid license covers this use, record it and apply the permitted-use decision. If only style or AI resemblance is found without validated artwork reuse, investigate that signal; do not draft a copying notice from that alone.



### The short explanation to say aloud

‘Artists register the original and record their rules. CreatorProof checks submitted or discovered images against those references, checks the intended use, and keeps clear evidence. In the final product, partner apps will use the Firewall API to allow, hold or block a use before publication. A human reviews flagged cases and approves any licensing or removal action.’



## 13. Find a saved case and decode the terms

*TEAMMATE · QUICK REFERENCE*

Use the stored comparisons for a quick walkthrough. The glossary explains the technical names in plain language.



| Name you may hear | Plain-language job |

| --- | --- |

| SHA-256 / perceptual hash | Exact-file ID / quick visual fingerprint. |

| SSCD / SIFT / ORB / MAGSAC | Find likely copies, then test matching details and alignment. |

| Sightengine / local fallbacks | Check AI-origin indicators, separately from copying. |

| CSD / C2PA | Advisory resemblance / checks on existing signed image history. |

| Rights Passport / license | Artist's preference card / recorded agreed permission. |

| Evidence Matrix / ledger | Eight questions about a scan / the artwork's creation timeline. |

| Firewall API / connector | Partner gate before use / source that supplies discoverable images. |

| Next.js / FastAPI / storage | The screens / backend coordinator / private files and database records. |



### Use the saved comparisons during the pitch



Open **Admin → Stored cases**. Select full-image republication, cropped publication or the AI sky edit. Show both pictures, open Detailed evidence, then Prepare notice. Images, measurements and drafts are saved; reopening does not run inference. The collection uses project-owned comparison images and real scans, not established third-party infringement cases. The API and storage must remain running.


