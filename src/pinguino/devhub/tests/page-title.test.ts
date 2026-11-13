import { afterEach, describe, expect, it } from 'vitest';
import { DEVHUB_TITLE, formatPageTitle, setPageTitle } from '../src/page-title';

describe('formatPageTitle', () => {
  it('joins segments and appends the site title', () => {
    expect(formatPageTitle(['Versions', 'My Add-on'])).toBe(
      'Versions :: My Add-on :: Add-ons for Firefox',
    );
  });

  it('drops empty/undefined segments', () => {
    // The dashboard passes only the context segment.
    expect(formatPageTitle([DEVHUB_TITLE])).toBe(
      'Developer Hub :: Add-ons for Firefox',
    );
    // An add-on name that hasn't loaded yet is skipped.
    expect(formatPageTitle(['Versions', undefined])).toBe(
      'Versions :: Add-ons for Firefox',
    );
  });
});

describe('setPageTitle', () => {
  afterEach(() => {
    document.title = '';
  });

  it('writes the formatted title to the document', () => {
    setPageTitle(['Request Support', DEVHUB_TITLE]);
    expect(document.title).toBe(
      'Request Support :: Developer Hub :: Add-ons for Firefox',
    );
  });
});
