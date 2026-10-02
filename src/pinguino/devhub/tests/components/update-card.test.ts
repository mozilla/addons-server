import { describe, expect, it } from 'vitest';
import type { UpdateCard } from '../../src/components/update-card';
import '../../src/components/update-card';
import type { Update } from '../../src/data';
import { mount } from '../helpers/fixture';

const baseUpdate: Update = {
  id: 'u1',
  approved: true,
  title: 'Your version is approved.',
  message: 'Congrats!',
  version: '3.2.1',
  versionStatus: 'Approved',
  tags: ['Live', 'AMO'],
  date: 'Sep 2 2025',
};

async function card(item: Partial<Update>) {
  const el = await mount<UpdateCard>('update-card', {
    item: { ...baseUpdate, ...item },
  });
  return el.shadowRoot as ShadowRoot;
}

describe('update-card', () => {
  it('renders an approved update with a success dot and status badge', async () => {
    const root = await card({ approved: true, versionStatus: 'Approved' });

    expect(root.querySelector('moz-status-dot')?.getAttribute('type')).toBe(
      'success',
    );
    const badge = root.querySelector('.foot moz-status-badge');
    expect(badge?.getAttribute('type')).toBe('success');
    expect(badge?.textContent?.trim()).toBe('Approved');
  });

  it('renders a flagged update with a warning dot and status badge', async () => {
    const root = await card({
      approved: false,
      versionStatus: 'Pending Approval',
    });

    expect(root.querySelector('moz-status-dot')?.getAttribute('type')).toBe(
      'warning',
    );
    expect(
      root.querySelector('.foot moz-status-badge')?.getAttribute('type'),
    ).toBe('warning');
  });

  it('omits the status badge when versionStatus is empty', async () => {
    const root = await card({ versionStatus: '' });
    expect(root.querySelector('.foot moz-status-badge')).toBeNull();
  });

  it('renders the title, message, version and each tag', async () => {
    const root = await card({ tags: ['Live', 'AMO', 'Beta'] });

    expect(root.querySelector('.title')?.textContent).toContain(
      'Your version is approved.',
    );
    expect(root.querySelector('.message')?.textContent?.trim()).toBe(
      'Congrats!',
    );
    const foot = root.querySelector('.foot')?.textContent ?? '';
    expect(foot).toContain('Version 3.2.1');
    for (const tag of ['Live', 'AMO', 'Beta']) {
      expect(foot).toContain(tag);
    }
  });
});
