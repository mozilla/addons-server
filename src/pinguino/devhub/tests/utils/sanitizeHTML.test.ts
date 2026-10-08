// @vitest-environment jsdom
// DOMPurify relies on DOM internals happy-dom doesn't fully implement (it
// silently strips allowed tags); jsdom is the environment DOMPurify targets.
import { describe, expect, it } from 'vitest';
import { sanitizeHTML } from '../../src/utils/sanitizeHTML';

describe('sanitizeHTML', () => {
  it('returns an empty string for nullish input', () => {
    expect(sanitizeHTML(null)).toBe('');
    expect(sanitizeHTML(undefined)).toBe('');
  });

  it('strips all tags by default, keeping text content', () => {
    expect(sanitizeHTML('<b>hi</b> <i>there</i>')).toBe('hi there');
  });

  it('keeps allowed tags and their safe attributes', () => {
    const out = sanitizeHTML('<a href="https://amo.test/x">link</a>', ['a']);
    expect(out).toContain('href="https://amo.test/x"');
    expect(out).toContain('>link</a>');
  });

  it('drops disallowed tags even when others are allowed', () => {
    const out = sanitizeHTML('<a href="/x">ok</a><script>evil()</script>', [
      'a',
    ]);
    expect(out).toContain('<a');
    expect(out).not.toContain('<script');
    expect(out).not.toContain('evil()');
  });

  it('removes event-handler, class and style attributes', () => {
    const out = sanitizeHTML(
      '<a href="/x" onclick="evil()" class="c" style="color:red">y</a>',
      ['a'],
    );
    expect(out).not.toContain('onclick');
    expect(out).not.toContain('class');
    expect(out).not.toContain('style');
    expect(out).toContain('href="/x"');
  });

  it('allows an attribute when explicitly permitted', () => {
    const out = sanitizeHTML('<a href="/x" class="c">y</a>', ['a'], ['class']);
    expect(out).toContain('class="c"');
  });
});
