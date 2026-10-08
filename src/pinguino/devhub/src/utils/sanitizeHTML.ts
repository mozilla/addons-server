import DOMPurify from 'dompurify';

// Adapted from addons-frontend's sanitizeHTML (src/amo/utils/index.js): we don't
// fully trust HTML the API returns, so run it through DOMPurify and keep only an
// explicit allowlist of tags/attributes. Returns a string for Lit's unsafeHTML
// directive (addons-frontend returns { __html } for React's
// dangerouslySetInnerHTML).
export function sanitizeHTML(
  text: string | null | undefined,
  allowTags: string[] = [],
  allowAttributes: string[] = [],
): string {
  const forbiddenAttributes = ['class', 'style'];
  return DOMPurify.sanitize(text ?? '', {
    ALLOWED_TAGS: allowTags,
    ALLOW_DATA_ATTR: false,
    ALLOW_ARIA_ATTR: false,
    SANITIZE_NAMED_PROPS: true,
    FORBID_ATTR: forbiddenAttributes.filter(
      (attrName) => !allowAttributes.includes(attrName),
    ),
    ADD_ATTR: allowAttributes,
  });
}
