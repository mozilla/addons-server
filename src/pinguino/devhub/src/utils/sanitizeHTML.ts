import DOMPurify from 'dompurify';

export const ACTIVITY_TAGS = ['a'];

export const MARKDOWN_TAGS = [
  'a',
  'abbr',
  'acronym',
  'b',
  'blockquote',
  'code',
  'em',
  'i',
  'li',
  'ol',
  'strong',
  'ul',
];

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

// A wrapper around sanitizeHTML for developer-generated HTML, allowing only a safe
// subset of tags and converting newlines to <br />.
export function sanitizeUserHTML(text: string | null | undefined): string {
  const allowTags = ['br', ...MARKDOWN_TAGS];
  return sanitizeHTML(nl2br(text), allowTags);
}

// Convert new lines to HTML breaks.  Copied from addons-frontend's nl2br function.
export function nl2br(text?: string | null): string {
  return (text || '').replace(/(\r\n|\r|\n)(?!<\/?(li|ul|ol)>)/g, '<br />');
}
