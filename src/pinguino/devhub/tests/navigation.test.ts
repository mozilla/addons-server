import { describe, expect, it, vi } from 'vitest';
import {
  classicPath,
  interceptOutOfAppLinks,
  isDashboardPath,
  isInAppPath,
  pageParam,
} from '../src/navigation';

describe('isInAppPath', () => {
  it('matches the base and its descendants', () => {
    expect(isInAppPath('/developers', '/developers')).toBe(true);
    expect(isInAppPath('/developers/', '/developers')).toBe(true);
    expect(isInAppPath('/developers/addon/x', '/developers')).toBe(true);
  });

  it('rejects paths outside the base', () => {
    expect(isInAppPath('/en-US/firefox/addon/x', '/developers')).toBe(false);
    expect(isInAppPath('/', '/developers')).toBe(false);
    // A sibling prefix must not count as in-app.
    expect(isInAppPath('/developers-foo', '/developers')).toBe(false);
  });
});

describe('interceptOutOfAppLinks', () => {
  // Run before the intercept listener (registration order within the capture
  // phase) so navigation is suppressed even when intercept stops propagation.
  function clickSpy(href: string) {
    const navGuard = (e: Event) => e.preventDefault();
    window.addEventListener('click', navGuard, { capture: true });
    const cleanup = interceptOutOfAppLinks('/developers');

    const anchor = document.createElement('a');
    anchor.href = href;
    document.body.append(anchor);

    const e = new MouseEvent('click', {
      bubbles: true,
      composed: true,
      cancelable: true,
      button: 0,
    });
    const spy = vi.spyOn(e, 'stopImmediatePropagation');
    anchor.dispatchEvent(e);

    cleanup();
    window.removeEventListener('click', navGuard, { capture: true });
    return spy;
  }

  it('stops a same-origin link outside the base from reaching the router', () => {
    expect(
      clickSpy(`${location.origin}/en-US/firefox/addon/x`),
    ).toHaveBeenCalledOnce();
  });

  it('leaves in-app links for the router to handle', () => {
    expect(
      clickSpy(`${location.origin}/developers/addon/x`),
    ).not.toHaveBeenCalled();
  });

  it('suppresses the native jump for same-page hash links but keeps the component handler', () => {
    const cleanup = interceptOutOfAppLinks('/pinguino');
    const anchor = document.createElement('a');
    anchor.href = `${location.origin}${location.pathname}#listing-details`;
    document.body.append(anchor);

    const e = new MouseEvent('click', {
      bubbles: true,
      composed: true,
      cancelable: true,
      button: 0,
    });
    const prevent = vi.spyOn(e, 'preventDefault');
    const stop = vi.spyOn(e, 'stopImmediatePropagation');
    anchor.dispatchEvent(e);
    cleanup();

    // Router bails on defaultPrevented; the component's own listener still runs.
    expect(prevent).toHaveBeenCalledOnce();
    expect(stop).not.toHaveBeenCalled();
  });
});

describe('isDashboardPath', () => {
  it('is the base alone, not the pages under it', () => {
    expect(isDashboardPath('/developers', '/developers')).toBe(true);
    expect(isDashboardPath('/developers/', '/developers')).toBe(true);
    expect(isDashboardPath('/developers/addon/x', '/developers')).toBe(false);
    expect(isDashboardPath('/developers/feed/x', '/developers')).toBe(false);
  });
});

describe('classicPath', () => {
  it('translates the add-on feed tab to the classic feed URL', () => {
    expect(classicPath('/developers/addon/my-addon/feed', '/developers')).toBe(
      '/developers/feed/my-addon',
    );
  });

  it('leaves paths classic has no counterpart for alone', () => {
    for (const path of [
      '/developers/',
      '/developers/addon/my-addon',
      '/developers/addon/my-addon/listing',
      '/developers/feed/my-addon',
      '/en-US/firefox/addon/my-addon',
    ]) {
      expect(classicPath(path, '/developers')).toBe(path);
    }
  });
});

describe('pageParam', () => {
  it('reads a positive page from the query string', () => {
    expect(pageParam('?page=3')).toBe(3);
  });

  it('falls back to page 1 for absent, zero, negative or junk values', () => {
    for (const search of [
      '',
      '?page=0',
      '?page=-2',
      '?page=abc',
      '?page=1.5',
    ]) {
      expect(pageParam(search)).toBe(1);
    }
  });
});
