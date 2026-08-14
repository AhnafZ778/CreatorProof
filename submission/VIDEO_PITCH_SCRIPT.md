# CreatorProof — 3-Minute Video Pitch

**Runtime target:** 2:58–3:00
**Narration:** ElevenLabs, single voice
**Composition:** ~78% real screen recording · ~17% AI-generated b-roll · ~5% type cards

---

## How to use this document

1. Work through **§1 Pre-production** first. The demo data has to exist before you record anything, and there is one section of the homepage you must *not* film.
2. Generate the six b-roll clips using the master prompts in **§6**. Do this early — you will need retries.
3. Record the ElevenLabs narration in **nine separate takes**, one per beat, using the settings in **§2**. Separate files give you control over pacing in the edit; one long take does not.
4. Capture the screen recordings from the shot list in **§1.3**.
5. Assemble against the timeline in **§3**, using the beat sheet in **§4** as the edit script.

Placeholders appear inline as `[CLIP-01]` … `[CLIP-06]`. Every one of them has a matching master prompt in §6 under the same number.

---

## §1 Pre-production

### 1.1 Demo data you must create before recording

The demo only lands if the match is real and recovered live on camera. Prepare this in advance:

| # | Asset | Why |
|---|---|---|
| A | 8–12 genuinely human-made artworks registered into the **`artist-library`** catalog through the Artist portal | The catalog has to be non-trivial or the coverage panel looks empty |
| B | One obviously AI-generated image, held back | For the registration-gate refusal moment at 1:15 |
| C | One **derivative** of a registered work: horizontally mirrored, cropped to ~60%, re-saved as JPEG twice | This is the hero moment. It must be a hard case, not an identical copy |
| D | One completely unrelated image | Optional: shows a clean PASS if you have spare seconds |

Generate asset **C** from a registered original:

```python
from PIL import Image, ImageOps
import io

src = Image.open("registered-original.png").convert("RGB")
w, h = src.size

# mirror, then crop to 60% of area from an off-centre anchor
img = ImageOps.mirror(src)
cw, ch = int(w * 0.775), int(h * 0.775)
img = img.crop((int(w * 0.14), int(h * 0.10), int(w * 0.14) + cw, int(h * 0.10) + ch))

# two generations of JPEG loss, the way a real repost degrades
for quality in (72, 58):
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality)
    img = Image.open(io.BytesIO(buf.getvalue())).convert("RGB")

img.save("candidate-repost.jpg", "JPEG", quality=90)
```

> **Rehearse the scan once before recording.** Confirm it returns a match and that the evidence workspace draws correspondences. If it returns review instead of match, use a slightly gentler crop (70%) — a live match is worth more than a hard case that only half-lands.

### 1.2 Do not film this

The homepage carries a scrolling statistics marquee with figures such as **99.8% AI-Origin Precision**, **99.4% SSCD Recall**, **140+ Countries** and **10,000+ Creator Profiles**. Those numbers are not backed by anything in the repository.

**Scroll past that band, or cut around it.** The entire pitch rests on the claim that this project is honest about what it does not know. One unbacked statistic on screen hands a judge a reason to disbelieve everything else. If you have time before submission, delete the marquee or replace the figures with the measured ones (98.1% match recall / 0 false matches / 364 benchmark cases).

### 1.3 Screen recording shot list

Record at **2560×1440 or higher, 60 fps**, then downscale to 1080p in the edit — downscaled footage is visibly sharper than natively recorded 1080p. Browser in fullscreen, no bookmarks bar, no notifications, no visible tabs.

| Shot | Duration to capture | Content |
|---|---|---|
| S1 | 20 s | Homepage hero, slow scroll through the pipeline diagram. Stop before the stats marquee. |
| S2 | 15 s | Artist portal: dropping in the AI image, the refusal appearing with score and threshold |
| S3 | 12 s | Artist portal: registering a legitimate work, receipt appearing |
| S4 | 20 s | Checker portal: dropping in `candidate-repost.jpg`, stage timeline running |
| S5 | 20 s | The three lane panels resolving, copy lane reaching its verdict |
| S6 | 30 s | Evidence workspace: correspondence lines on the pixels, aligned region, mirrored label |
| S7 | 15 s | Coverage panel and the signed receipt / proof status |

Move the cursor **slowly and deliberately**. Fast cursor movement is the single most common thing that makes a demo look amateur. Capture roughly twice as much of each shot as you think you need.

---

## §2 ElevenLabs voice direction

### Voice selection

Choose a voice with these properties rather than a specific preset name, since the library changes:

- **Register:** mid-to-low, adult, unhurried
- **Accent:** neutral international English — clarity matters more than character for a judging panel
- **Texture:** slightly dry, minimal breathiness, no "announcer" brightness
- **Reference feel:** documentary narration, not advertising voiceover

Avoid anything energetic or "excited". The script's persuasive strategy is restraint. An enthusiastic read actively fights it.

### Settings

| Parameter | Value | Reason |
|---|---|---|
| Model | Current highest-quality multilingual model (not the low-latency/turbo tier) | Turbo models trade prosody for speed; prosody is the whole point here |
| Stability | **45%** | Low enough for natural variation, high enough to avoid wobble on long sentences |
| Similarity | **80%** | Keeps the voice consistent across nine separate takes |
| Style exaggeration | **0–10%** | Anything higher introduces artefacts and over-performs the read |
| Speaker boost | On | — |

### Getting the pacing right

ElevenLabs responds to punctuation, not to stage directions. Use these in the input text:

- `—` (em dash) → a short beat, roughly 250 ms
- `…` (ellipsis) → a longer hesitation
- A line break between sentences → a fuller stop
- Full stops instead of commas → **the single most effective pacing tool.** "Mirrored. Recoloured. Selling." reads far slower and heavier than the same words joined by commas.

Do not write "(pause)" into the text — it will be spoken. The pauses marked in §4 are **edit-timeline pauses**: render each beat separately and space them apart on the timeline.

**Render nine files:** `vo-01-hook.mp3` … `vo-09-close.mp3`, matching the beats in §4.

---

## §3 Master timeline

| Time | Beat | Audio | Visual |
|---|---|---|---|
| 0:00–0:06 | Cold open | VO 1 begins | `[CLIP-01]` |
| 0:06–0:15 | Hook completes | VO 1 | Title card: *CreatorProof* |
| 0:15–0:24 | The chain | VO 2 | S1 homepage hero, slow scroll |
| 0:24–0:29 | The chain | VO 2 continues | `[CLIP-02]` |
| 0:29–0:38 | The chain resolves | VO 2 | S1 pipeline diagram |
| 0:38–0:40 | **Silence** | — | Black |
| 0:40–0:46 | The reframe | VO 3 | `[CLIP-03]` |
| 0:46–0:55 | Three questions | VO 3 | Type card: the three questions, one line at a time |
| 0:55–1:15 | The solution | VO 4 | S1 pipeline / lane cards |
| 1:15–1:28 | Demo — registration gate | VO 5 | S2 |
| 1:28–1:44 | Demo — the candidate | VO 6 | S3 → S4 |
| 1:44–1:58 | Demo — the lanes | VO 7 | S5 |
| 1:58–2:15 | Demo — the evidence | VO 8 | S6 |
| 2:15–2:21 | The seal | VO 9 begins | `[CLIP-04]` |
| 2:21–2:32 | Proof | VO 9 | S7 |
| 2:32–2:36 | **Silence** | — | S7 holds |
| 2:36–2:41 | Impact | VO 10 | `[CLIP-05]` |
| 2:41–2:48 | Impact resolves | VO 10 | S6 detail, held still |
| 2:48–2:53 | The future | VO 11 | `[CLIP-06]` |
| 2:53–2:58 | Close | VO 12 | End card |
| 2:58–3:00 | — | — | End card holds, audio out |

---

## §4 The script

Read the **VO** column aloud exactly as written. Everything else is direction.

---

### VO 1 — Cold open · 0:00–0:15

> An illustrator spends three weeks on a commission.
>
> Four months later, she finds it on a product listing in another country.
>
> Mirrored. Recoloured. Selling.

**On screen**
`[CLIP-01]` runs 0:00–0:06 under the first two lines. At 0:06, cut to black for 4 frames, then a centred title card: **CreatorProof** in Geist, white on black, small, no tagline yet.

**Direction**
The three one-word sentences are the hook. They must be delivered slowly, with a real gap between each. Do not let the edit rush them.

---

### VO 2 — The chain · 0:15–0:38

> The brand that published it never meant to steal anything. An agency supplied the asset. The agency got it from a freelancer.
>
> Nobody in that chain checked — because before you publish an image, there is no practical way to check.
>
> So everyone hopes. And someone loses.

**On screen**
0:15–0:24 homepage hero (S1), slow scroll. 0:24–0:29 `[CLIP-02]` under "nobody in that chain checked". 0:29–0:38 back to S1, resting on the pipeline diagram.

**Direction**
This beat removes the villain. The panel arrived expecting a story about theft; you are telling them it is a story about a missing process. That reframe is what makes the rest feel inevitable.

---

### VO 3 — The reframe · 0:40–0:55

> Here is what the whole industry gets wrong.
>
> "Is this safe to publish" is not one question. It is three.
>
> Does it reuse a registered work? Was a generative model involved? Does it resemble a living creator?

**On screen**
Two seconds of black before this beat starts — the only hard silence in the film, and it is doing work.
0:40–0:46 `[CLIP-03]`, the prism splitting one beam into three.
0:46–0:55 type card, the three questions appearing one line at a time in the lane colours: cyan, pink, amber.

**Direction**
This is the intellectual centre of the pitch. Land "It is three" and hold. The clip and the type card should feel like the answer arriving, not like decoration.

---

### VO 4 — The solution · 0:55–1:15

> Every tool on the market answers one of those and implies the others — with a single number you cannot audit.
>
> CreatorProof answers all three, keeps them separate, and refuses to merge them into a verdict.
>
> Three AI lanes. Three findings. One record you can check yourself.

**On screen**
S1 — the pipeline diagram and the three lane cards on the homepage.

---

### VO 5 — Demo: the gate · 1:15–1:28

> An artist registers her work.
>
> Before anything enters the registry, an AI-origin ensemble screens it — and refuses what a generative model likely produced. It shows the score. It shows the threshold. So the artist can argue with it.

**On screen**
S2 — the AI image is dropped in, the refusal appears. Let the refusal card sit on screen for a full second before cutting.

---

### VO 6 — Demo: the candidate · 1:28–1:44

> Now someone about to publish drops in a candidate.
>
> This file has been mirrored, cropped to sixty percent, and re-compressed twice.

**On screen**
S3 briefly (a legitimate work registering, receipt appearing), then S4 — the candidate dropping in, the stage timeline running.

**Direction**
Say the three transformations plainly and let the stage timeline run in silence afterwards. The waiting is tension; do not fill it.

---

### VO 7 — Demo: the lanes · 1:44–1:58

> The copy lane finds it.
>
> Not because a model scored it highly — but because classical geometry physically aligned this image onto the original, and then the pixels agreed.

**On screen**
S5 — the three lane panels resolving. Make sure all three are visible at once at least momentarily, so the separation is seen and not merely asserted.

---

### VO 8 — Demo: the evidence · 1:58–2:15

> And it shows you exactly why.
>
> Every matched point. The aligned region. The structural agreement.
>
> You can disagree with the machine — using the same evidence the machine used.

**On screen**
S6 — the evidence workspace, correspondence lines drawn across the pixels. This is the visual peak of the film. Give it room and let it play almost undisturbed.

---

### VO 9 — The proof · 2:15–2:32

> Then the whole result is sealed. Canonicalised, signed, written into an append-only log, and committed to a public blockchain as thirty-two bytes.
>
> Not the artwork. The hash.
>
> And a second organisation can bind its own key to that same record.

**On screen**
2:15–2:21 `[CLIP-04]`, the seal forming. 2:21–2:32 S7 — the coverage panel and the receipt.
Hold on S7 in silence from 2:32 to 2:36.

---

### VO 10 — The impact · 2:36–2:48

> That changes what a disagreement looks like.
>
> The artist has a timestamp. The brand has a defensible record. And neither of them has to trust us — because the proof does not depend on us.

**On screen**
2:36–2:41 `[CLIP-05]`, the handover. 2:41–2:48 a still, held frame from S6.

---

### VO 11 — The future · 2:48–2:53

> Every registration makes the next check stronger. Every counter-signature makes the network harder to leave.

**On screen**
`[CLIP-06]`, the lattice forming.

---

### VO 12 — Close · 2:53–2:58

> CreatorProof.
>
> See what matches. Prove what you checked.

**On screen**
End card: the wordmark, the two-line tagline, and nothing else. Hold to 3:00 with the audio already out.

**Direction**
Drop volume slightly on the final line rather than raising it. Then stop. Do not add a "thank you".

---

## §5 Edit and sound design

- **Music.** One sparse bed, low. Piano or a sustained synth pad, no percussion until 1:15, and duck it 6 dB under every VO line. If in doubt, less music. Silence is a tool this script uses on purpose at 0:38 and 2:32 — do not paper over either gap.
- **The b-roll clips carry their own generated ambience.** Bring it in at roughly −18 dB so it colours the cut without competing with narration. Mute any generated audio that contains anything resembling speech.
- **Cuts.** Hard cuts throughout. One exception: a 12-frame dissolve from `[CLIP-03]` into the type card at 0:46, because that transition is meant to feel like a realisation rather than an edit.
- **Screen recordings.** Apply a very slight scale ramp (100% → 103% over the shot) so static UI does not feel frozen. Keep it subtle enough to be invisible.
- **Text on screen.** Geist for everything, matching the product. Never more than seven words on a card. No animated text effects.
- **Colour.** Grade the b-roll to match the product UI: crushed blacks, cool highlights. The clips and the screen recordings must look like the same film.
- **Export.** 1080p, H.264, 12–16 Mbps, AAC audio at 192 kbps. Loudness normalise to −14 LUFS.

---

## §6 Master video prompts

### 6.1 How to use these

These are written for a modern text-to-video model with native audio generation. The structure follows the ordering such models weight most heavily: **subject → action → scene → camera → lighting → style → audio**, with the most important content front-loaded.

Four rules that matter more than any individual word:

1. **One action per clip.** Chained actions ("she turns, then reaches, then opens") are the primary cause of morphing artefacts.
2. **One camera move per clip.** Never combine a dolly with a pan.
3. **State exclusions as scene facts, not negations.** "The surface is bare" works. "No text on the surface" often produces text.
4. **Generate three takes per clip and keep one.** Budget for this. A beautiful five-second clip beats a flawed ten-second one, which is why every clip here is five or six seconds.

### 6.2 Style contract

Prepend this to every generation so the six clips read as one film.

```
STYLE CONTRACT
Cinematic macro photography, 24fps, shot on a 50mm prime with shallow depth of field.
Palette: near-black background, cool desaturated blue-grey mid-tones, deeply crushed
blacks, clean specular highlights. Low-key single-source lighting with faint atmospheric
haze. Fine natural 35mm film grain. Locked or a single very slow camera move under 15cm
of travel. Physically plausible motion and materials throughout.
The frame is clean and unmarked: bare surfaces, no lettering, no symbols, no interfaces,
no branding of any kind. No human face is visible. No lens flare, no chromatic
aberration, no digital sharpening halo.
Audio: quiet naturalistic ambience only, recorded close and dry. Silence underneath.
```

### 6.3 Negative prompt

Apply to every clip.

```
text, letters, words, numbers, captions, subtitles, watermark, logo, signature,
user interface, buttons, icons, human face, portrait, crowd, fast motion, camera shake,
handheld, zoom burst, lens flare, chromatic aberration, oversaturated colour, neon pink
and green, plastic CGI look, morphing geometry, extra fingers, warped hands, distorted
perspective, music, singing, speech, voiceover, narration
```

---

### `[CLIP-01]` — The making · 6 seconds · 0:00

**Purpose:** Establish the human labour that everything downstream is about. Intimate, quiet, unhurried.

```
A single human hand holding a fine sable brush, seen from directly above, drawing one
slow continuous stroke of deep indigo pigment across heavy cotton watercolour paper.
The pigment blooms outward into the paper fibres as the stroke passes, the wet edge
catching the light.

The setting is a dark studio at night; only the working surface is lit and everything
beyond it falls away into black. The paper is bare apart from this single stroke.

Camera: locked overhead macro shot, no movement, the brush tip entering frame from the
lower right.

Lighting: one soft diffused source from the upper left at a low angle, raking across the
paper so its texture is visible, falling off steeply to pure black at the frame edges.

Style: cinematic macro, 50mm, shallow depth of field with the brush tip in sharp focus
and the far paper softly out of focus. Cool blue-grey grade, fine 35mm grain.

Audio: the dry whisper of bristles moving across textured paper, very close and quiet,
with faint room tone beneath it. Nothing else.
```

**Accept if:** the stroke is continuous, the hand has five fingers and does not deform, the paper stays unmarked otherwise.
**Retry if:** the hand morphs mid-stroke, the pigment behaves like smoke, any mark resembling a letter appears.

---

### `[CLIP-02]` — The chain · 5 seconds · 0:24

**Purpose:** Uncontrolled reproduction. An image passing through a supply chain, degrading, nobody accountable.

```
A single sheet of thick matte photographic paper standing upright in darkness, seen
edge-on at a slight angle. Identical copies of it slide out from behind it one after
another in a fanning cascade to the right, each copy offset by a few centimetres and
each one visibly flatter and greyer than the one before it.

The setting is an empty black void with no floor and no horizon. The sheets are blank
and unprinted.

Camera: a single very slow push in along the axis of the fan, no pan, no tilt.

Lighting: one hard raking light from the far left so each sheet casts a crisp shadow
onto the next, the shadows deepening as the cascade recedes.

Style: cinematic product photography, 50mm, shallow depth of field with the front sheet
sharp and the tail of the cascade falling out of focus. Cool desaturated grade,
deep blacks, fine grain.

Audio: the dry slide of paper against paper, a soft accelerating shuffle, then quiet.
```

**Accept if:** the copies stay rectangular and rigid, the cascade reads clearly as duplication.
**Retry if:** the sheets bend like cloth, the count is chaotic, printed content appears on them.

---

### `[CLIP-03]` — Three questions · 6 seconds · 0:40

**Purpose:** The intellectual pivot of the film. One question becoming three. This clip has to be the most beautiful thing in the video.

```
A solid triangular glass prism resting on a black reflective surface. One narrow beam of
pure white light enters it from the left, and exits the far face as exactly three separate
coloured beams — one cyan, one magenta-pink, one warm amber — which travel outward to the
right, remain parallel and distinct, and hold steady. Three beams and only three.

The setting is an empty black void with a faint drift of atmospheric haze, just enough for
each beam to be visible along its whole length.

Camera: one slow lateral dolly from left to right across roughly fifteen centimetres,
holding the prism centred. No other movement.

Lighting: the beams are the only light in the scene. Everything they do not touch is black.
The prism glows internally where the light refracts through it.

Style: cinematic macro, 50mm, shallow depth of field focused on the exit face of the prism.
High contrast, deep blacks, fine grain, physically accurate refraction and caustics.

Audio: a single sustained low tone with a faint high shimmer as the beams separate.
No music.
```

**Accept if:** there are exactly three exit beams, in the right three colours, and they stay separate.
**Retry if:** you get a full rainbow spectrum, two beams, four or more beams, or the colours bleed together. *This is the most likely clip to need retries — the count and the colour set are both things video models handle poorly. Generate five takes for this one.*

---

### `[CLIP-04]` — The seal · 6 seconds · 2:15

**Purpose:** The evidence being committed. Should feel final and mechanical rather than magical.

```
A single translucent block of dark crystal suspended and slowly rotating in empty
darkness. Thin lines of pale blue light travel inward across each of its faces from the
edges toward the centre, converging simultaneously at a small geometric core inside the
block, which then snaps into place with a hard click and holds perfectly still and lit.

The setting is a black void with a faint cold haze. The crystal's surfaces are smooth
and unmarked.

Camera: one slow five-degree orbit around the block, no push, no tilt.

Lighting: the internal light is the only source, casting soft blue refractions through
the crystal onto nothing. Deep black surroundings.

Style: cinematic macro product rendering, 50mm, shallow depth of field, physically
accurate glass refraction and internal reflection. Cool blue grade, crushed blacks,
fine grain.

Audio: a single low resonant mechanical click at the moment the core locks, followed by
a quiet sustained hum that fades.
```

**Accept if:** the convergence resolves cleanly and the final state holds still.
**Retry if:** the light keeps moving after the lock, the crystal deforms, the effect reads as fire or smoke rather than light.

---

### `[CLIP-05]` — The handover · 5 seconds · 2:36

**Purpose:** Restitution. Two parties, one record, both hold it. The only clip with any warmth.

```
Two human hands over a dark wooden table, one passing a single unmarked sheet of heavy
cream paper to the other. The receiving hand's fingers close around the edge of the sheet
and the handover completes. One movement only.

The setting is a dark room with a single shallow pool of light on the table; everything
beyond the hands is black. The sheet is completely blank.

Camera: locked, at table height, no movement.

Lighting: one soft cool key from above and behind, plus a single warm rim light at low
intensity catching the edges of both hands, so the shot is cool overall with one point of
warmth.

Style: cinematic, 50mm, very shallow depth of field with the edge of the paper in sharp
focus and both wrists falling soft. Fine grain, deep blacks.

Audio: the soft rustle of heavy paper and one quiet breath of room tone.
```

**Accept if:** both hands have correct anatomy throughout, the handover completes within the clip.
**Retry if:** fingers multiply or merge, the paper folds unnaturally, a face enters frame.

---

### `[CLIP-06]` — The network · 5 seconds · 2:48

**Purpose:** Scale, without saying the word "global". Restrained, not a spinning globe.

```
A wide field of small isolated points of pale blue light scattered at varying depths in
darkness. Thin luminous lines begin to draw between them, one pair at a time in quick
succession, until a loose three-dimensional lattice has formed across the whole field.
As the last connection completes, the entire lattice brightens by a small amount and
holds.

The setting is deep black space with a faint cold haze that catches the light of the
lines. There are no continents, no globe, no map.

Camera: one extremely slow push forward into the field. No rotation.

Lighting: the points and lines are the only light sources.

Style: cinematic, 50mm, shallow depth of field with the nearest points softly out of
focus and the mid-field sharp. Cool blue monochrome grade, deep blacks, fine grain.

Audio: a soft high shimmer as each connection forms, over a low sustained pad that rises
very slightly at the end.
```

**Accept if:** the lattice builds progressively and the final state is stable.
**Retry if:** it reads as a generic "digital network" stock shot, a globe appears, or the lines pulse rhythmically like a screensaver.

---

### 6.4 Fallback shots

If any clip will not resolve after five attempts, substitute rather than ship something flawed:

| Clip | Substitute |
|---|---|
| `[CLIP-01]` | Static macro of raking light across cotton paper texture, 6 s, very slow dolly |
| `[CLIP-02]` | Extend S1 homepage scroll and let VO 2 carry the beat alone |
| `[CLIP-03]` | Build it in the edit: one white line splitting into three coloured lines, animated in After Effects. Honestly, this may look better than a generated version |
| `[CLIP-04]` | Screen recording of the proof status panel, slow push in |
| `[CLIP-05]` | Hold a still frame from the evidence workspace |
| `[CLIP-06]` | Slow push into the homepage pipeline diagram |

---

## §7 Final quality checklist

- [ ] Runtime is between 2:50 and 3:00
- [ ] The statistics marquee does not appear in a single frame
- [ ] All three lane panels are visible simultaneously at least once
- [ ] The match shown is a genuine live result, not a mock-up
- [ ] The two deliberate silences at 0:38 and 2:32 survived the edit
- [ ] No generated clip contains text, a face, or anything resembling speech
- [ ] Narration is normalised to −14 LUFS and never clips
- [ ] The final frame holds for a full two seconds after the audio ends
- [ ] Someone who has never seen the project can explain what it does after one viewing
