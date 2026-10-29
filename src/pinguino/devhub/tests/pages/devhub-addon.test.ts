import { describe, expect, it } from 'vitest';
import type { DevhubAddon } from '../../src/pages/addon/templates/devhub-addon';
import '../../src/pages/addon/templates/devhub-addon';
import type { Addon } from '../../src/data';
import { ADDON_STATUS, queryClient, queryKeys } from '../../src/data';
import { mount, settle } from '../helpers/fixture';

const addon: Addon = {
  slug: 'ad-blocker',
  name: 'Ad Blocker',
  kind: 'extension',
  icon: 'extension',
  status: ADDON_STATUS.public,
  version: '3.2.1',
  lastUpdated: 'Aug 18 2025',
  visibility: 'visible',
  channels: ['listed'],
};

describe('devhub-addon', () => {
  it('defaults to the listing editor tab and renders the shell', async () => {
    queryClient.setQueryData(queryKeys.addons, [addon]);
    const el = await mount<DevhubAddon>('devhub-addon', { slug: 'ad-blocker' });
    await settle(el);
    const root = el.shadowRoot as ShadowRoot;

    const header = root.querySelector('addon-manage-header');
    expect((header as unknown as { addon: Addon })?.addon.name).toBe(
      'Ad Blocker',
    );

    const tabs = [...root.querySelectorAll('moz-segmented-control-item')].map(
      (t) => t.getAttribute('value'),
    );
    expect(tabs).toEqual(['versions', 'feed', 'edit', 'statistics']);
    expect(
      root.querySelector('moz-segmented-control')?.getAttribute('value'),
    ).toBe('edit');
    expect(root.querySelector('addon-listing')).not.toBeNull();
  });

  it('stubs (not the listing) for a non-edit tab', async () => {
    queryClient.setQueryData(queryKeys.addons, [addon]);
    const el = await mount<DevhubAddon>('devhub-addon', {
      slug: 'ad-blocker',
      tab: 'versions',
    });
    await settle(el);
    const root = el.shadowRoot as ShadowRoot;

    expect(
      root.querySelector('moz-segmented-control')?.getAttribute('value'),
    ).toBe('versions');
    expect(root.querySelector('addon-listing')).toBeNull();
    expect(root.querySelector('coming-soon')).not.toBeNull();
  });

  it('stubs an unimplemented Django tab', async () => {
    queryClient.setQueryData(queryKeys.addons, [addon]);
    const el = await mount<DevhubAddon>('devhub-addon', {
      slug: 'ad-blocker',
      tab: 'invitation',
    });
    await settle(el);
    const root = el.shadowRoot as ShadowRoot;

    expect(root.querySelector('coming-soon')).not.toBeNull();
    expect(root.querySelector('addon-listing')).toBeNull();
  });

  it('selecting a tab navigates to its sub-URL', async () => {
    queryClient.setQueryData(queryKeys.addons, [addon]);
    const el = await mount<DevhubAddon>('devhub-addon', { slug: 'ad-blocker' });
    await settle(el);
    const root = el.shadowRoot as ShadowRoot;

    root.querySelector('moz-segmented-control')?.dispatchEvent(
      new CustomEvent('moz-segmented-control:change', {
        detail: { value: 'statistics' },
      }),
    );
    expect(location.pathname).toBe('/developers/addon/ad-blocker/statistics');
  });

  it('shows a not-found message when no add-on matches the slug', async () => {
    queryClient.setQueryData(queryKeys.addons, [addon]);
    const el = await mount<DevhubAddon>('devhub-addon', { slug: 'unknown' });
    await settle(el);
    const root = el.shadowRoot as ShadowRoot;

    expect(root.querySelector('addon-manage-header')).toBeNull();
    expect(root.textContent).toContain("couldn't find that add-on");
  });
});
