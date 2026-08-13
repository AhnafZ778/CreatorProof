/**
 * Ed25519 signature verification (RFC 8032) for the in-browser evidence verifier.
 *
 * WebCrypto gained native Ed25519 only recently and it is still absent from some
 * shipping browsers, so a BigInt implementation is the portable floor. When the
 * platform does offer Ed25519 it is used instead, because it is both faster and
 * constant-time. Verification uses public data only; no secret ever reaches the
 * browser.
 */

const P = (1n << 255n) - 19n;
const L = 2n ** 252n + 27742317777372353535851937790883648493n;
const D = -121665n * modInverse(121666n, P) % P;
const SQRT_M1 = modPow(2n, (P - 1n) / 4n, P);

type Point = { x: bigint; y: bigint; z: bigint; t: bigint };

const BASE_Y = 4n * modInverse(5n, P) % P;

function mod(value: bigint, modulus: bigint = P): bigint {
  const result = value % modulus;
  return result >= 0n ? result : result + modulus;
}

function modPow(base: bigint, exponent: bigint, modulus: bigint): bigint {
  let result = 1n;
  let current = mod(base, modulus);
  let power = exponent;
  while (power > 0n) {
    if (power & 1n) result = (result * current) % modulus;
    current = (current * current) % modulus;
    power >>= 1n;
  }
  return result;
}

function modInverse(value: bigint, modulus: bigint): bigint {
  return modPow(mod(value, modulus), modulus - 2n, modulus);
}

function recoverX(y: bigint, sign: bigint): bigint | null {
  if (y >= P) return null;
  const y2 = mod(y * y);
  const numerator = mod(y2 - 1n);
  const denominator = mod(mod(D * y2) + 1n);
  let x = mod(numerator * modPow(denominator, (P + 3n) / 8n, P));
  if (mod(denominator * x * x - numerator) !== 0n) x = mod(x * SQRT_M1);
  if (mod(denominator * x * x - numerator) !== 0n) return null;
  if ((x & 1n) !== sign) x = mod(-x);
  return x;
}

const IDENTITY: Point = { x: 0n, y: 1n, z: 1n, t: 0n };

function makePoint(x: bigint, y: bigint): Point {
  return { x, y, z: 1n, t: mod(x * y) };
}

function add(a: Point, b: Point): Point {
  const aa = mod((a.y - a.x) * (b.y - b.x));
  const bb = mod((a.y + a.x) * (b.y + b.x));
  const cc = mod(2n * a.t * b.t * D);
  const dd = mod(2n * a.z * b.z);
  const e = bb - aa;
  const f = dd - cc;
  const g = dd + cc;
  const h = bb + aa;
  return { x: mod(e * f), y: mod(g * h), z: mod(f * g), t: mod(e * h) };
}

function multiply(point: Point, scalar: bigint): Point {
  let result = IDENTITY;
  let addend = point;
  let remaining = mod(scalar, L);
  while (remaining > 0n) {
    if (remaining & 1n) result = add(result, addend);
    addend = add(addend, addend);
    remaining >>= 1n;
  }
  return result;
}

function equal(a: Point, b: Point): boolean {
  return mod(a.x * b.z - b.x * a.z) === 0n && mod(a.y * b.z - b.y * a.z) === 0n;
}

function decodePoint(bytes: Uint8Array): Point | null {
  if (bytes.length !== 32) return null;
  const copy = Uint8Array.from(bytes);
  const sign = BigInt((copy[31] >> 7) & 1);
  copy[31] &= 0x7f;
  const y = leToBigInt(copy);
  const x = recoverX(y, sign);
  return x === null ? null : makePoint(x, y);
}

function leToBigInt(bytes: Uint8Array): bigint {
  let value = 0n;
  for (let index = bytes.length - 1; index >= 0; index -= 1) {
    value = (value << 8n) | BigInt(bytes[index]);
  }
  return value;
}

async function sha512(data: Uint8Array): Promise<Uint8Array> {
  const buffer = data.slice().buffer as ArrayBuffer;
  return new Uint8Array(await crypto.subtle.digest("SHA-512", buffer));
}

function concat(...parts: Uint8Array[]): Uint8Array {
  const total = parts.reduce((sum, part) => sum + part.length, 0);
  const out = new Uint8Array(total);
  let offset = 0;
  for (const part of parts) {
    out.set(part, offset);
    offset += part.length;
  }
  return out;
}

async function verifyNative(
  publicKey: Uint8Array,
  message: Uint8Array,
  signature: Uint8Array,
): Promise<boolean | null> {
  try {
    const key = await crypto.subtle.importKey(
      "raw",
      publicKey.slice().buffer as ArrayBuffer,
      { name: "Ed25519" },
      false,
      ["verify"],
    );
    return await crypto.subtle.verify(
      { name: "Ed25519" },
      key,
      signature.slice().buffer as ArrayBuffer,
      message.slice().buffer as ArrayBuffer,
    );
  } catch {
    return null;
  }
}

export async function verify(
  publicKey: Uint8Array,
  message: Uint8Array,
  signature: Uint8Array,
): Promise<boolean> {
  if (publicKey.length !== 32 || signature.length !== 64) return false;
  const native = await verifyNative(publicKey, message, signature);
  if (native !== null) return native;

  const rBytes = signature.slice(0, 32);
  const s = leToBigInt(signature.slice(32));
  if (s >= L) return false;
  const a = decodePoint(publicKey);
  const r = decodePoint(rBytes);
  if (a === null || r === null) return false;

  const digest = await sha512(concat(rBytes, publicKey, message));
  const k = mod(leToBigInt(digest), L);
  const base = makePoint(recoverX(BASE_Y, 0n) as bigint, BASE_Y);
  return equal(multiply(base, s), add(r, multiply(a, k)));
}

export function hexToBytes(hex: string): Uint8Array {
  const clean = hex.startsWith("0x") ? hex.slice(2) : hex;
  if (clean.length % 2 !== 0) throw new Error("Invalid hex length");
  const out = new Uint8Array(clean.length / 2);
  for (let index = 0; index < out.length; index += 1) {
    out[index] = Number.parseInt(clean.slice(index * 2, index * 2 + 2), 16);
  }
  return out;
}

export function base64ToBytes(value: string): Uint8Array {
  const normalized = value.replace(/-/g, "+").replace(/_/g, "/");
  const padded = normalized + "=".repeat((4 - (normalized.length % 4)) % 4);
  const binary = atob(padded);
  const out = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) out[index] = binary.charCodeAt(index);
  return out;
}
