import { describe, expect, it, vi } from 'vitest';
import { interceptOutOfAppLinks, isInAppPath } from '../src/navigation';

describe('isInAppPath', () => {
  it('matches the base and its descendants', () => {
    expect(isInAppPath('/pinguino', '/pinguino')).toBe(true);
    expect(isInAppPath('/pinguino/', '/pinguino')).toBe(true);
    expect(isInAppPath('/pinguino/addon/x', '/pinguino')).toBe(true);
  });

  it('rejects paths outside the base', () => {
    expect(isInAppPath('/en-US/firefox/addon/x', '/pinguino')).toBe(false);
    expect(isInAppPath('/', '/pinguino')).toBe(false);
    // A sibling prefix must not count as in-app.
    expect(isInAppPath('/pinguino-foo', '/pinguino')).toBe(false);
  });
});

describe('interceptOutOfAppLinks', () => {
  // Run before the intercept listener (registration order within the capture
  // phase) so navigation is suppressed even when intercept stops propagation.
  function clickSpy(href: string) {
    const navGuard = (e: Event) => e.preventDefault();
    window.addEventListener('click', navGuard, { capture: true });
    const cleanup = interceptOutOfAppLinks('/pinguino');

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
      clickSpy(`${location.origin}/pinguino/addon/x`),
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
