import { describe, expect, it, vi } from 'vitest';
import type { DevhubHeader } from '../../src/components/devhub-header';
import '../../src/components/devhub-header';
import { mount } from '../helpers/fixture';

async function header() {
  const el = await mount<DevhubHeader>('devhub-header');
  return el.shadowRoot as ShadowRoot;
}

describe('devhub-header', () => {
  it('shows a link to switch back to the classic devhub', async () => {
    const root = await header();
    // rel="external" (the Django endpoint, not an in-app route) uniquely
    // identifies the switch link among the nav anchors.
    const link = root.querySelector('a[rel="external"]');
    expect(link).not.toBeNull();
    expect(link?.getAttribute('href')).toBe('/developers/switch-pinguino');
    expect(link?.textContent?.trim()).toBe('Switch back to old Developer Hub');
  });

  it('on click, navigates to the endpoint with the current path', async () => {
    const root = await header();
    const link = root.querySelector('a[rel="external"]') as HTMLAnchorElement;

    // The handler reads the live location at click time and drives a full
    // navigation, so stub it to assert the resulting URL.
    const loc = { pathname: '/developers/addon/x', search: '', href: '' };
    vi.stubGlobal('location', loc);

    const event = new MouseEvent('click', { bubbles: true, cancelable: true });
    link.dispatchEvent(event);

    // Default navigation is blocked in favour of the enriched URL.
    expect(event.defaultPrevented).toBe(true);
    expect(loc.href).toBe(
      '/developers/switch-pinguino?path=%2Fdevelopers%2Faddon%2Fx',
    );
  });
});
