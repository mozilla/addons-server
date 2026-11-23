// The AMO session id, read once at startup and held in memory for the session.
//
// src/olympia/developers/views.py::serve_pinguino injects the session id into
// the html, setting the `token` attribute of the <pinguino-app> element in
// index.html. We read it and immediately strip it from the DOM so other scripts
// (extensions, injected code) can't scrape it afterwards.
function takeSessionToken(): string {
  const el =
    typeof document === 'undefined'
      ? null
      : document.querySelector('pinguino-app');
  const token = el?.getAttribute('token') ?? '';
  el?.removeAttribute('token');
  return token && token !== 'INSERT_TOKEN_HERE' ? token : '';
}

export const session = takeSessionToken();
