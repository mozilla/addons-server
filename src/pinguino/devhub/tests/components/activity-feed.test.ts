import { describe, expect, it } from 'vitest';
import type { ActivityFeed } from '../../src/components/activity-feed';
import '../../src/components/activity-feed';
import type { ActivityPage, Update } from '../../src/data';
import { queryClient, VERSION_STATUS } from '../../src/data';
import { mount, settle } from '../helpers/fixture';

const update = (id: string): Update => ({
  id,
  title: 'Your version is approved.',
  message: 'Congrats!',
  version: '3.2.1',
  versionStatus: VERSION_STATUS.public,
  channel: 'listed',
  date: 'Sep 2 2025',
  user: 'Kate',
  addonName: 'Ad Blocker',
  addonSlug: 'ad-blocker',
});

async function feed(page: number, data: ActivityPage) {
  queryClient.setQueryData(['activity', 'ad-blocker', page], data);
  const el = await mount<ActivityFeed>('activity-feed', {
    slug: 'ad-blocker',
    page,
  });
  await settle(el);
  return el.shadowRoot as ShadowRoot;
}

describe('activity-feed', () => {
  it('renders a card per activity entry', async () => {
    const root = await feed(1, {
      items: [update('1'), update('2')],
      total: 2,
    });
    expect(root.querySelectorAll('update-card')).toHaveLength(2);
    expect(root.querySelector('.empty')).toBeNull();
  });

  it('shows an empty state rather than a bare list', async () => {
    const root = await feed(1, {
      items: [],
      total: 0,
    });
    expect(root.querySelector('.empty')?.textContent).toContain(
      'No activity yet',
    );
  });

  it('sizes the pager from the total, not the length of this page', async () => {
    const root = await feed(2, {
      items: [update('1')],
      total: 42,
    });
    const pager = root.querySelector('app-pagination');
    expect(pager?.page).toBe(2);
    expect(pager?.total).toBe(42);
  });
});
