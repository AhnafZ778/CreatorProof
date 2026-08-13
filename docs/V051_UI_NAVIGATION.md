# CreatorProof v0.5.1 UI navigation contract

Build: `0.5.1 / NAVIGATION-SPECTRUM-2026.08.09`

This revision changes presentation and navigation. It does not change the validated v0.5 copy-fusion
equations or style-provider semantics.

## Page hierarchy

1. The sticky release bar links directly to **Workbench**, **Analysis**, and **System**.
2. The three-step strip makes the operating sequence explicit: **Register work → Run a scan → Explore analysis**.
3. Registration and scanning use different accent colours and active/completed states.
4. A completed scan opens the analysis workspace at `#analysis`.

## Analysis navigation

The desktop workspace keeps a five-mode navigator visible beside the active evidence view. Responsive
layouts move that navigator above the evidence without changing mode order.

| Mode | Lane | User question |
| --- | --- | --- |
| Case summary | Start here | What did the system decide, and which signals agree? |
| Copy regions | Copy | Did the same visual structure survive editing, cropping, or retouching? |
| Aligned structure | Copy | Which retouch-resistant structural measurements support the pair? |
| Creator style | Style | Does a different composition resemble a multi-work creator profile? |
| Style map | Style diagnostic | Which low-level visual factors contribute to the style comparison? |

Colour is semantic rather than decorative: cyan/blue identifies copy evidence, amber/pink identifies
style evidence, and purple identifies the case summary. Every active mode includes a short explanation
of when it should be used.

## Accessibility and responsive acceptance

- Mode controls are real buttons with `aria-pressed` state and visible keyboard focus.
- Disabled style modes say that a creator profile is required.
- Major sections use stable anchors and scroll offsets beneath the sticky header.
- At medium widths the navigator becomes a horizontally scrollable row of full mode cards.
- At phone widths the navigator becomes a single-column list and the active-view action occupies a full row.
- Colour never carries the meaning alone; every lane and state also has a text label.

## Verification

Run:

```bash
cd apps/web
npm run typecheck
npm run build
```

Then verify the register, scan, anchor navigation, all five mode buttons, feature-pair toggle, style tile
inspection, and OpenRouter explanation button in a browser with real scan data.
