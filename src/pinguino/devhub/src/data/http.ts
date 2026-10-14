// Low-level HTTP for the AMO API. One place owns the base URL, session auth,
// JSON parsing, and error typing — endpoint functions in ./api stay one-liners.
// Auth is the AMO session id (sent as `Authorization: Session <id>`), supplied
// via env; see .env.example.

const SESSION = import.meta.env.VITE_AMO_SESSION_ID;
const BASE = import.meta.env.VITE_AMO_API_BASE ?? '/api/v5';

// Carries the HTTP status and any validation errors so callers can branch (a
// future 401 interceptor) or map errors onto the inputs that caused them.
// `fields` is keyed by the API field name; `detail` is the general (non-field)
// message; `message` is the combined summary for generic callers.
export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
    readonly fields: Record<string, string> = {},
    readonly detail = '',
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

// Parse a failed response. DRF validation errors come back as
// { field: ["msg", …] } (plus { detail } / { non_field_errors } for general
// ones); split the field errors out so forms can attach them to inputs, and
// build a readable summary for anywhere that only shows a message.
async function parseError(res: Response): Promise<{
  message: string;
  fields: Record<string, string>;
  detail: string;
}> {
  const fallback = `AMO API responded ${res.status}`;
  try {
    const body = await res.json();
    if (typeof body === 'string')
      return { message: body || fallback, fields: {}, detail: body };
    const fields: Record<string, string> = {};
    const general: string[] = [];
    for (const [key, value] of Object.entries(
      body as Record<string, unknown>,
    )) {
      const text = Array.isArray(value) ? value.join(' ') : String(value);
      if (key === 'detail' || key === 'non_field_errors') general.push(text);
      else fields[key] = text;
    }
    const detail = general.join(' • ');
    const message =
      [
        ...general,
        ...Object.entries(fields).map(([k, t]) => `${k}: ${t}`),
      ].join(' • ') || fallback;
    return { message, fields, detail };
  } catch {
    return { message: fallback, fields: {}, detail: '' };
  }
}

export async function apiFetch<T>(
  path: string,
  { method = 'GET', body }: { method?: string; body?: unknown } = {},
): Promise<T> {
  // FormData (file uploads) must go as multipart — let the browser set the
  // content-type/boundary and send it as-is rather than JSON.
  const isForm = body instanceof FormData;
  const res = await fetch(`${BASE}${path}`, {
    method,
    headers: {
      ...(SESSION ? { authorization: `Session ${SESSION}` } : {}),
      ...(body != null && !isForm
        ? { 'content-type': 'application/json' }
        : {}),
    },
    body: body == null ? undefined : isForm ? body : JSON.stringify(body),
  });
  if (!res.ok) {
    // TODO(auth): on 401, clear the session and route to login once FxA lands.
    const { message, fields, detail } = await parseError(res);
    throw new ApiError(res.status, message, fields, detail);
  }
  // DELETE and other 204s have no body to parse.
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T);
}
