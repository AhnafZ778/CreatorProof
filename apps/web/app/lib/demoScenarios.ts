/**
 * Competition demo mode.
 *
 * Sample images are drawn in the browser rather than shipped as files: nothing
 * copyrighted enters the repository, the fixtures cannot drift from the code,
 * and every scenario is reproducible on a projector with no network. Each
 * scenario states up front which lane it is meant to exercise and what the
 * honest expected outcome is — including the ones that should end in review
 * rather than a clean pass.
 */

export type ScenarioId = "exact-copy" | "transformed-copy" | "ai-origin" | "creator-profile";

/** Which evidence lane a scenario is built to exercise. Also selects the card's
 *  accent, so the colour on screen always names a real lane. */
export type LaneKey = "copy" | "origin" | "profile";

export type DemoScenario = {
  id: ScenarioId;
  title: string;
  lane: string;
  laneKey: LaneKey;
  question: string;
  expectation: string;
  caveat: string;
  intendedUse: string;
  referenceCount: number;
};

export const DEMO_SCENARIOS: DemoScenario[] = [
  {
    id: "exact-copy",
    title: "Exact reuse of a registered work",
    lane: "COPY LANE",
    laneKey: "copy",
    question: "Someone re-uploads a work that is already in the catalog.",
    expectation:
      "A verified visual match, matched-region evidence, and an action shaped by the recorded rights path.",
    caveat: "A match is evidence of reuse of a stored file, not a legal finding of infringement.",
    intendedUse: "marketing/social",
    referenceCount: 1,
  },
  {
    id: "transformed-copy",
    title: "Cropped and recompressed copy",
    lane: "COPY LANE",
    laneKey: "copy",
    question: "The same artwork is cropped, rescaled and saved again at lower quality.",
    expectation:
      "Shared visual structure is recovered through matched-region analysis, even after common transformations.",
    caveat: "Heavy transformation can drop below threshold; that is a limit of the scan, not proof of originality.",
    intendedUse: "marketing/social",
    referenceCount: 1,
  },
  {
    id: "ai-origin",
    title: "Image carrying an AI-origin marker",
    lane: "AI-ORIGIN LANE",
    laneKey: "origin",
    question: "A candidate carries a visible generation label and no catalog match.",
    expectation:
      "AI-origin intelligence surfaces the generation label while visual matching independently checks the catalog.",
    caveat: "An AI-origin signal is a probabilistic indicator, never a determination that a person did not make the work.",
    intendedUse: "editorial",
    referenceCount: 1,
  },
  {
    id: "creator-profile",
    title: "Different content, familiar creator style",
    lane: "CREATOR-PROFILE LANE",
    laneKey: "profile",
    question: "New content resembles a registered creator's palette and structure.",
    expectation:
      "Creator intelligence surfaces the strongest visual resemblance across the registered profile.",
    caveat: "Style resemblance is advisory context for a human reviewer and is not evidence of copying.",
    intendedUse: "marketing/social",
    referenceCount: 3,
  },
];

type Canvas = HTMLCanvasElement;

function makeCanvas(width = 512, height = 512): { canvas: Canvas; ctx: CanvasRenderingContext2D } {
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("This browser did not provide a 2D canvas context.");
  return { canvas, ctx };
}

function paintArtwork(ctx: CanvasRenderingContext2D, seed: number, palette: string[]) {
  const { width, height } = ctx.canvas;
  const gradient = ctx.createLinearGradient(0, 0, width, height);
  gradient.addColorStop(0, palette[0]);
  gradient.addColorStop(1, palette[1]);
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, width, height);

  // A small deterministic PRNG keeps every run of the demo identical.
  let state = seed >>> 0;
  const random = () => {
    state = (state * 1664525 + 1013904223) >>> 0;
    return state / 0xffffffff;
  };

  for (let index = 0; index < 26; index += 1) {
    ctx.globalAlpha = 0.35 + random() * 0.45;
    ctx.fillStyle = palette[2 + Math.floor(random() * (palette.length - 2))];
    const size = 24 + random() * 150;
    const x = random() * width;
    const y = random() * height;
    if (index % 3 === 0) {
      ctx.beginPath();
      ctx.arc(x, y, size / 2, 0, Math.PI * 2);
      ctx.fill();
    } else if (index % 3 === 1) {
      ctx.fillRect(x - size / 2, y - size / 2, size, size * 0.6);
    } else {
      ctx.beginPath();
      ctx.moveTo(x, y - size / 2);
      ctx.lineTo(x + size / 2, y + size / 2);
      ctx.lineTo(x - size / 2, y + size / 2);
      ctx.closePath();
      ctx.fill();
    }
  }
  ctx.globalAlpha = 1;
}

async function toFile(canvas: Canvas, name: string, quality = 0.92): Promise<File> {
  const blob = await new Promise<Blob | null>((resolve) =>
    canvas.toBlob(resolve, "image/jpeg", quality),
  );
  if (!blob) throw new Error("The browser could not encode the demo image.");
  return new File([blob], name, { type: "image/jpeg" });
}

const PALETTES: Record<string, string[]> = {
  primary: ["#12283a", "#204b5e", "#8fbf9f", "#d7a55f", "#c96f6f"],
  sibling: ["#14202f", "#1f4a63", "#8dbda2", "#d3a262", "#bf7373"],
};

export type DemoBundle = {
  references: Array<{ file: File; title: string; claimant: string }>;
  candidate: File;
  candidateLabel: string;
  scenario: DemoScenario;
};

/** Build the reference works and candidate image for one scenario. */
export async function buildScenario(scenario: DemoScenario): Promise<DemoBundle> {
  const { canvas: refCanvas, ctx: refCtx } = makeCanvas();
  paintArtwork(refCtx, 20260810, PALETTES.primary);
  const referenceFile = await toFile(refCanvas, "demo-reference.jpg");
  const references = [
    { file: referenceFile, title: "Demo reference — harbour study", claimant: "Demo Creator" },
  ];

  if (scenario.id === "creator-profile") {
    for (let index = 1; index < scenario.referenceCount; index += 1) {
      const { canvas, ctx } = makeCanvas();
      paintArtwork(ctx, 20260810 + index * 7919, PALETTES.primary);
      references.push({
        file: await toFile(canvas, `demo-reference-${index + 1}.jpg`),
        title: `Demo reference — series ${index + 1}`,
        claimant: "Demo Creator",
      });
    }
  }

  let candidate: File;
  let candidateLabel: string;

  if (scenario.id === "exact-copy") {
    candidate = new File([referenceFile], "demo-candidate-exact.jpg", { type: "image/jpeg" });
    candidateLabel = "Byte-identical re-upload of the registered work";
  } else if (scenario.id === "transformed-copy") {
    const { canvas, ctx } = makeCanvas(384, 384);
    const bitmap = await createImageBitmap(refCanvas);
    ctx.drawImage(bitmap, 64, 40, 400, 400, 0, 0, 384, 384);
    candidate = await toFile(canvas, "demo-candidate-transformed.jpg", 0.55);
    candidateLabel = "Cropped, rescaled and recompressed derivative";
  } else if (scenario.id === "ai-origin") {
    const { canvas, ctx } = makeCanvas();
    paintArtwork(ctx, 777001, PALETTES.sibling);
    ctx.fillStyle = "rgba(8, 12, 18, 0.72)";
    ctx.fillRect(0, canvas.height - 74, canvas.width, 74);
    ctx.fillStyle = "#f4f7fb";
    ctx.font = "bold 30px system-ui, sans-serif";
    ctx.fillText("Made with AI", 26, canvas.height - 28);
    candidate = await toFile(canvas, "demo-candidate-ai.jpg");
    candidateLabel = "Unrelated content carrying a visible AI-generation label";
  } else {
    const { canvas, ctx } = makeCanvas();
    paintArtwork(ctx, 424242, PALETTES.primary);
    candidate = await toFile(canvas, "demo-candidate-style.jpg");
    candidateLabel = "New composition sharing the registered creator's palette";
  }

  return { references, candidate, candidateLabel, scenario };
}
