import { afterEach, describe, expect, it, vi } from 'vitest';
import type { SwitchBackLink } from '../../src/components/switch-back-link';
import '../../src/components/switch-back-link';
import { mount } from '../helpers/fixture';

async function link(props: Partial<SwitchBackLink> = {}) {
  const el = await mount<SwitchBackLink>('switch-back-link', props);
  return (el.shadowRoot as ShadowRoot).querySelector(
    'a[rel="external"]',
  ) as HTMLAnchorElement;
}

describe('switch-back-link', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('renders the switch-pinguino endpoint as a no-JS fallback href', async () => {
    const a = await link();
    expect(a).not.toBeNull();
    expect(a.getAttribute('href')).toBe('/developers/switch-pinguino');
  });

  it('falls back to standalone wording with no slotted text', async () => {
    const a = await link();
    expect(a.textContent?.trim()).toBe('Switch back');
  });

  it('on click, navigates to the endpoint with the current path', async () => {
    const a = await link();

    // The handler reads the live location at click time and drives a full
    // navigation, so stub it to assert the resulting URL.
    const loc = { pathname: '/developers/addon/x', search: '', href: '' };
    vi.stubGlobal('location', loc);

    const event = new MouseEvent('click', { bubbles: true, cancelable: true });
    a.dispatchEvent(event);

    // Default navigation is blocked in favour of the enriched URL.
    expect(event.defaultPrevented).toBe(true);
    expect(loc.href).toBe(
      '/developers/switch-pinguino?path=%2Fdevelopers%2Faddon%2Fx',
    );
  });
});
