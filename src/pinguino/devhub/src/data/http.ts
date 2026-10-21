// Low-level HTTP for the AMO API. One place owns the base URL, session auth,
// JSON parsing, and error typing — endpoint functions in ./api stay one-liners.
// Auth is the AMO session id (sent as `Authorization: Session <id>`).

const BASE = import.meta.env.VITE_AMO_API_BASE ?? '/api/v5';

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

// The AMO session id lives in an HttpOnly cookie we can't read from JS, so the
// browser sends it automatically on this same-origin request and the session
// endpoint echoes it back for us to replay as an Authorization header.
//
// Memoised at module scope so we resolve it exactly once per full page load and
// share that one request across every concurrent API call. Resolves to null
// when logged out (the endpoint 401s), in which case we send no auth header.
let sessionIdPromise: Promise<string | null> | undefined;

async function fetchSessionId(): Promise<string | null> {
  try {
    const res = await fetch(`${BASE}/accounts/session/`, {
      credentials: 'same-origin',
    });
    if (!res.ok) return null;
    const { session_id } = (await res.json()) as { session_id: string };
    return session_id ?? null;
  } catch {
    return null;
  }
}

function getSessionId(): Promise<string | null> {
  if (!sessionIdPromise) {
    sessionIdPromise = fetchSessionId();
  }
  return sessionIdPromise;
}

export async function apiFetch<T>(
  path: string,
  { method = 'GET', body }: { method?: string; body?: unknown } = {},
): Promise<T> {
  const session = await getSessionId();
  const res = await fetch(`${BASE}${path}`, {
    method,
    headers: {
      ...(session ? { authorization: `Session ${session}` } : {}),
      ...(body ? { 'content-type': 'application/json' } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    // TODO(auth): on 401, clear the session and route to login once FxA lands.
    throw new ApiError(res.status, `AMO API responded ${res.status}`);
  }
  return (await res.json()) as T;
}
