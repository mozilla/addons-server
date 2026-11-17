import { afterEach, describe, expect, it } from 'vitest';
import { formatPageTitle, setPageTitle } from '../src/page-title';

describe('formatPageTitle', () => {
  it('joins exactly the segments given, without adding a site suffix', () => {
    // setPageTitle supplies the site title; formatPageTitle is a pure join.
    expect(formatPageTitle(['Versions', 'My Add-on'])).toBe(
      'Versions :: My Add-on',
    );
  });

  it('drops empty, null, and undefined segments', () => {
    expect(
      formatPageTitle(['Versions', undefined, 'Add-ons for Firefox']),
    ).toBe('Versions :: Add-ons for Firefox');
    expect(formatPageTitle([null, '', 'Add-ons for Firefox'])).toBe(
      'Add-ons for Firefox',
    );
    expect(formatPageTitle([])).toBe('');
  });
});

// Mirrors Django's dev_page_title(): "<page> :: <context> :: Add-ons for Firefox",
// where <context> is the add-on name, or "Developer Hub" when omitted.
describe('setPageTitle', () => {
  afterEach(() => {
    document.title = '';
  });

  it('uses the given context (e.g. the add-on name) when provided', () => {
    setPageTitle('Versions', 'My Add-on');
    expect(document.title).toBe('Versions :: My Add-on :: Add-ons for Firefox');
  });

  it('defaults the context to the Developer Hub', () => {
    setPageTitle('Request Support');
    expect(document.title).toBe(
      'Request Support :: Developer Hub :: Add-ons for Firefox',
    );
  });

  it('omits the page segment when there is no page (the dashboard)', () => {
    setPageTitle();
    expect(document.title).toBe('Developer Hub :: Add-ons for Firefox');
  });

  it('omits an empty page segment but keeps the context', () => {
    // e.g. devhub-addon's not-yet-implemented tabs pass an empty page.
    setPageTitle('', 'My Add-on');
    expect(document.title).toBe('My Add-on :: Add-ons for Firefox');
  });

  it('treats a null page like an absent one', () => {
    setPageTitle(null, 'My Add-on');
    expect(document.title).toBe('My Add-on :: Add-ons for Firefox');
  });
});
