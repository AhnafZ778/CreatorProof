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
            "Explain the supplied CreatorProof evidence in concise, confident plain language for a creative team. " +
            "Lead with the recorded decision, strongest evidence, and practical next step. " +
            "Describe source coverage, verified visual matching, AI-origin intelligence, creator-profile insight, " +
            "rights context, and proof as distinct layers of the same CreatorProof workflow. " +
            "Use the exact recorded status and policy action; never invent a result, change the policy, or claim " +
            "that a signal is present when it is not. Keep technical qualification details brief unless they directly " +
            "affect the recommended next step.",
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
