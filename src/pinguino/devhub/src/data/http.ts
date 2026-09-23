// Low-level HTTP for the AMO API. One place owns the base URL, session auth,
// JSON parsing, and error typing — endpoint functions in ./api stay one-liners.
// Auth is the AMO session id (sent as `Authorization: Session <id>`), supplied
// via env; see .env.example.

const SESSION = import.meta.env.VITE_AMO_SESSION_ID;
const AUTHOR = import.meta.env.VITE_AMO_AUTHOR;
const BASE = import.meta.env.VITE_AMO_API_BASE ?? '/api/v5';

// Only hit the API when we have both a session and an author to filter by;
// otherwise the app runs on built-in mock data (see ./mock).
export const apiConfigured = Boolean(SESSION && AUTHOR);
export const author = AUTHOR ?? '';

// Carries the HTTP status so callers (and a future 401 interceptor) can branch.
export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

export async function apiFetch<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: SESSION ? { authorization: `Session ${SESSION}` } : {},
  });
  if (!res.ok) {
    // TODO(auth): on 401, clear the session and route to login once FxA lands.
    throw new ApiError(res.status, `AMO API responded ${res.status}`);
  }
  return (await res.json()) as T;
}
