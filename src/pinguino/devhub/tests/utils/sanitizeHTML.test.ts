// @vitest-environment jsdom
// DOMPurify relies on DOM internals happy-dom doesn't fully implement (it
// silently strips allowed tags); jsdom is the environment DOMPurify targets.
import { describe, expect, it } from 'vitest';
import {
  nl2br,
  sanitizeHTML,
  sanitizeUserHTML,
} from '../../src/utils/sanitizeHTML';

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

describe('nl2br', () => {
  it('returns an empty string for nullish input', () => {
    expect(nl2br(null)).toBe('');
    expect(nl2br(undefined)).toBe('');
    expect(nl2br('')).toBe('');
  });

  it('converts the various newline forms to <br />', () => {
    expect(nl2br('a\nb')).toBe('a<br />b');
    expect(nl2br('a\r\nb')).toBe('a<br />b');
    expect(nl2br('a\rb')).toBe('a<br />b');
  });

  it('converts every newline in the string', () => {
    expect(nl2br('a\nb\nc')).toBe('a<br />b<br />c');
  });

  it('leaves text without newlines untouched', () => {
    expect(nl2br('no breaks here')).toBe('no breaks here');
  });

  it('does not add a break before list tags, but does elsewhere', () => {
    // Newlines before <ul>/<ol>/<li> (and their closing tags) are left as-is so
    // list markup is not padded with stray breaks; other newlines convert.
    expect(nl2br('one\ntwo\n<ul>\n<li>x</li>\n</ul>')).toBe(
      'one<br />two\n<ul>\n<li>x</li>\n</ul>',
    );
  });
});

describe('sanitizeUserHTML', () => {
  it('returns an empty string for nullish input', () => {
    expect(sanitizeUserHTML(null)).toBe('');
    expect(sanitizeUserHTML(undefined)).toBe('');
  });

  it('renders newlines as <br> breaks', () => {
    const out = sanitizeUserHTML('line one\nline two');
    expect(out).toContain('line one');
    expect(out).toContain('line two');
    expect(out).toContain('<br');
  });

  it('keeps the allowed markdown tags', () => {
    const out = sanitizeUserHTML('<strong>bold</strong> <em>italic</em>');
    expect(out).toContain('<strong>bold</strong>');
    expect(out).toContain('<em>italic</em>');
  });

  it('strips disallowed tags while keeping their text', () => {
    const out = sanitizeUserHTML('<script>evil()</script><b>safe</b>');
    expect(out).not.toContain('<script');
    expect(out).not.toContain('evil()');
    expect(out).toContain('<b>safe</b>');
  });
});
