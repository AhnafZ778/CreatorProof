import { NextResponse } from "next/server";

export async function POST(request: Request) {
  const apiKey = process.env.OPENROUTER_API_KEY?.trim();
  if (!apiKey) {
    return NextResponse.json(
      { error: "OPENROUTER_NOT_CONFIGURED" },
      { status: 503 },
    );
  }

  const input = await request.json();
  const serialized = JSON.stringify(input).slice(0, 20_000);
  const model = process.env.OPENROUTER_MODEL?.trim();
  const response = await fetch("https://openrouter.ai/api/v1/chat/completions", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${apiKey}`,
      "Content-Type": "application/json",
      "HTTP-Referer": process.env.OPENROUTER_SITE_URL ?? "http://localhost:3000",
      "X-OpenRouter-Title": "CreatorProof Evidence Explainer",
    },
    body: JSON.stringify({
      ...(model ? { model } : {}),
      max_tokens: 350,
      messages: [
        {
          role: "system",
          content:
            "Explain the supplied CreatorProof detector metrics in plain language. " +
            "Do not decide copyright infringement, ownership, or originality. " +
            "State the source-coverage status before explaining a no-match; incomplete, empty, " +
            "degraded, truncated, or failed scope can never be described as clearance. " +
            "Clearly separate the copy/derivative lane (SSCD plus verified geometry) from " +
            "the creator-profile resemblance lane (profile retrieval plus low-level diagnostics). Never " +
            "interpret style similarity as proof of model training, copying, or infringement. " +
            "Call out uncalibrated scores, weak single-work profiles, fallbacks, and missing AI signals. " +
            "The recorded policy action is an input to explain, never something you may change.",
        },
        { role: "user", content: serialized },
      ],
    }),
    cache: "no-store",
  });

  const body = await response.json();
  if (!response.ok) {
    return NextResponse.json(
      { error: "OPENROUTER_REQUEST_FAILED", details: body },
      { status: response.status },
    );
  }
  const explanation = body?.choices?.[0]?.message?.content;
  if (typeof explanation !== "string") {
    return NextResponse.json({ error: "OPENROUTER_RESPONSE_INVALID" }, { status: 502 });
  }
  return NextResponse.json({ explanation, model: body.model ?? model ?? "account-default" });
}
