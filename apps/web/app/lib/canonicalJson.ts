/**
 * RFC 8785 JSON Canonicalization Scheme.
 *
 * The API canonicalizes with the same rules in Python before signing, so the
 * browser must reproduce those exact bytes or a valid signature will look
 * invalid. Keys sort by UTF-16 code unit, which is what `Array.prototype.sort`
 * already does for strings.
 */

const ESCAPES: Record<string, string> = {
  "\b": "\\b",
  "\t": "\\t",
  "\n": "\\n",
  "\f": "\\f",
  "\r": "\\r",
  '"': '\\"',
  "\\": "\\\\",
};

function canonicalString(value: string): string {
  let out = '"';
  for (const char of value) {
    const escape = ESCAPES[char];
    if (escape) {
      out += escape;
    } else if (char < "\u0020") {
      out += `\\u${char.charCodeAt(0).toString(16).padStart(4, "0")}`;
    } else {
      out += char;
    }
  }
  return `${out}"`;
}

function canonicalNumber(value: number): string {
  if (!Number.isFinite(value)) throw new Error("JCS forbids NaN and Infinity");
  if (value === 0) return "0";
  // ECMAScript Number::toString is exactly what RFC 8785 specifies.
  return String(value);
}

export function canonicalize(value: unknown): string {
  if (value === null) return "null";
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "number") return canonicalNumber(value);
  if (typeof value === "string") return canonicalString(value);
  if (Array.isArray(value)) return `[${value.map(canonicalize).join(",")}]`;
  if (typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>).filter(
      ([, item]) => item !== undefined,
    );
    entries.sort(([left], [right]) => (left < right ? -1 : left > right ? 1 : 0));
    return `{${entries
      .map(([key, item]) => `${canonicalString(key)}:${canonicalize(item)}`)
      .join(",")}}`;
  }
  throw new Error(`Unsupported JCS value: ${typeof value}`);
}

export function canonicalBytes(value: unknown): Uint8Array {
  return new TextEncoder().encode(canonicalize(value));
}

export async function sha256Hex(data: Uint8Array): Promise<string> {
  const buffer = data.slice().buffer as ArrayBuffer;
  const digest = await crypto.subtle.digest("SHA-256", buffer);
  return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}
