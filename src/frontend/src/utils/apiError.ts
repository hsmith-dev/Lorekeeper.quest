/** Pull the backend's `detail` message out of an axios error, falling back to
 * a generic message when the error isn't one of ours (network failure, CORS,
 * etc.) or doesn't have the expected shape. */
export function apiErrorMessage(err: unknown, fallback = "Something went wrong. Try again."): string {
  const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
  return detail || fallback;
}
