import { describe, expect, it } from 'vitest';
import type { DevhubAddon } from '../../src/pages/devhub-addon';
import '../../src/pages/devhub-addon';
import type { Addon } from '../../src/data';
import { queryClient, queryKeys } from '../../src/data';
import { mount, settle } from '../helpers/fixture';

const addon: Addon = {
  slug: 'ad-blocker',
  name: 'Ad Blocker',
  kind: 'extension',
  icon: 'extension',
  statusLabel: 'Live add-on',
  version: '3.2.1',
  lastUpdated: 'Aug 18 2025',
  visibility: 'live',
  distribution: 'amo',
};

const heading = (root: ShadowRoot) =>
  root.querySelector('moz-page-header')?.getAttribute('heading');

describe('devhub-addon', () => {
  it('resolves the add-on name from the cached list by slug', async () => {
    queryClient.setQueryData(queryKeys.addons, [addon]);
    const el = await mount<DevhubAddon>('devhub-addon', { slug: 'ad-blocker' });
    await settle(el);
    const root = el.shadowRoot as ShadowRoot;

    expect(heading(root)).toBe('Manage: Ad Blocker');
    expect(root.querySelector('strong')?.textContent).toBe('Ad Blocker');
  });

  it('falls back to the slug when no matching add-on is cached', async () => {
    queryClient.setQueryData(queryKeys.addons, [addon]);
    const el = await mount<DevhubAddon>('devhub-addon', { slug: 'unknown' });
    await settle(el);
    const root = el.shadowRoot as ShadowRoot;

    expect(heading(root)).toBe('Manage: unknown');
  });
});
