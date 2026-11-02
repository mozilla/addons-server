import { describe, expect, it } from 'vitest';
import type { AddonVersion } from '../../src/components/addon-version/addon-version';
import '../../src/components/addon-version/addon-version';
import type { Addon, Version } from '../../src/data';
import { ADDON_STATUS, queryClient, queryKeys } from '../../src/data';
import { DEFAULT_VERSION, mount, settle } from '../helpers/fixture';

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

async function mountVersions(props: Partial<Addon>, versions: Version[]) {
  queryClient.setQueryData(queryKeys.versions('ad-blocker'), versions);
  const el = await mount<AddonVersion>('addon-version', {
    addon: { ...addon, ...props },
  });
  await settle(el);
  return el.shadowRoot as ShadowRoot;
}

function versionNumbers(section: Element | null | undefined): string[] {
  return [...(section?.querySelectorAll('.version-number') ?? [])].map(
    (n) => n.textContent?.trim() ?? '',
  );
}

describe('addon-version', () => {
  it('splits the current version from the other versions', async () => {
    const versions: Version[] = [
      { ...DEFAULT_VERSION, id: 1, version: '1.0', channel: 'listed' },
      { ...DEFAULT_VERSION, id: 2, version: '2.0', channel: 'unlisted' },
      { ...DEFAULT_VERSION, id: 3, version: '3.0', channel: 'enterprise' },
    ];
    const root = await mountVersions({ currentVersion: versions[0] }, versions);

    // The current_version is shown in the listed version section.
    const current = root.querySelector('.version-section.current');
    expect(current?.querySelector('.section-title')?.textContent).toContain(
      'Listed Version',
    );
    expect(versionNumbers(current)).toEqual(['1.0']);

    // And not in the 'other versions' section.
    const remaining = root.querySelector('.version-section:not(.current)');
    expect(versionNumbers(remaining)).toEqual(['2.0', '3.0']);

    // Only the listed version offers the add-on's visibility setting.
    expect(
      current?.querySelector('visibility-badge moz-radio-group'),
    ).not.toBeNull();
    expect(remaining?.querySelector('visibility-badge')).toBeNull();
  });

  it('highlights the pending listed version that would replace the current one', async () => {
    const unreviewed = {
      id: 1,
      url: '',
      size: 0,
      status: 'unreviewed',
    } as const;
    const versions: Version[] = [
      {
        ...DEFAULT_VERSION,
        id: 1,
        version: '1.0',
        channel: 'unlisted',
        file: unreviewed,
      },
      { ...DEFAULT_VERSION, id: 2, version: '2.0', file: unreviewed },
      { ...DEFAULT_VERSION, id: 3, version: '3.0', file: unreviewed },
      { ...DEFAULT_VERSION, id: 4, version: '4.0' },
      { ...DEFAULT_VERSION, id: 5, version: '5.0', file: unreviewed },
    ];
    const root = await mountVersions({ currentVersion: versions[3] }, versions);

    // Only the most recent is highlighted.
    const highlighted = [...root.querySelectorAll('.next-listed-version')];
    expect(highlighted.map((row) => versionNumbers(row))).toEqual([['5.0']]);
  });

  it('points an incomplete listing back to the submission flow', async () => {
    const root = await mountVersions({ status: ADDON_STATUS.incomplete }, [
      DEFAULT_VERSION,
    ]);
    const continueUrl = '/addon/ad-blocker/submit/details';

    // Popup is shown.
    const bar = root.querySelector('moz-message-bar');
    expect(bar?.getAttribute('heading')).toBe('Incomplete listing');
    expect(bar?.querySelector('moz-button')?.getAttribute('href')).toContain(
      continueUrl,
    );

    // Link changes.
    const versionButton = root.querySelector(
      '.version-row:not(.labels) .manage-button',
    );
    expect(versionButton?.textContent?.trim()).toBe('Continue Uploading');
    expect(versionButton?.getAttribute('href')).toContain(continueUrl);
  });

  it('does not show the incomplete listing message for other statuses', async () => {
    const root = await mountVersions({}, [DEFAULT_VERSION]);

    expect(root.querySelector('moz-message-bar')).toBeNull();
    const versionButton = root.querySelector(
      '.version-row:not(.labels) .manage-button',
    );
    expect(versionButton?.textContent?.trim()).toBe('Manage version');
  });
});
