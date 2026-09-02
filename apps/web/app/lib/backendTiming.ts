const READ_RETRY_ATTEMPT_MS = 12_000;

/** Mutations get one full attempt so a local timeout cannot overlap a live write. */
export function backendAttemptTimeout(
  method: string,
  retryable: boolean,
  remainingMs: number,
): number {
  const normalizedMethod = method.toUpperCase();
  const readOnly = normalizedMethod === "GET" || normalizedMethod === "HEAD";
  return retryable && readOnly
    ? Math.max(1, Math.min(READ_RETRY_ATTEMPT_MS, remainingMs))
    : Math.max(1, remainingMs);
}
