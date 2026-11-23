import { describe, expect, it, vi } from 'vitest';

const { updateVersion, replyToVersion } = vi.hoisted(() => ({
  updateVersion: vi.fn(async () => {}),
  replyToVersion: vi.fn(async () => {}),
}));
vi.mock('../../src/data', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../src/data')>()),
  updateVersion,
  replyToVersion,
}));

import type { VersionDetail } from '../../src/components/addon-version/version-detail';
import '../../src/components/addon-version/version-detail';
import type { ActivityPage, Addon, Update, Version } from '../../src/data';
import {
  ADDON_STATUS,
  queryClient,
  queryKeys,
  VERSION_STATUS,
} from '../../src/data';
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
  canChangeVisibility: true,
  channels: ['listed'],
};

const version: Version = {
  ...DEFAULT_VERSION,
  id: 7,
  version: '3.2.1',
  release_notes: 'Fixed bugs.',
  approval_notes: 'Run npm build.',
  source: '/source.zip',
};

const update: Update = {
  id: '1',
  title: 'Version approved.',
  message: '',
  version: '3.2.1',
  versionStatus: VERSION_STATUS.public,
  channel: 'listed',
  date: 'Sep 2 2025',
  addonName: 'Ad Blocker',
  addonSlug: 'ad-blocker',
};

async function mountDetail(
  v: Version | null,
  activity: Update[] = [],
  total = activity.length,
) {
  if (v) queryClient.setQueryData(queryKeys.version('ad-blocker', v.id), v);
  queryClient.setQueryData(
    ['activity', 'infinite', 'ad-blocker', v?.id ?? 404],
    {
      pages: [{ items: activity, total } satisfies ActivityPage],
      pageParams: [1],
    },
  );
  const el = await mount<VersionDetail>('version-detail', {
    addon,
    versionId: v?.id ?? 404,
  });
  await settle(el);
  return { el, root: el.shadowRoot as ShadowRoot };
}

async function openActivity({
  el,
  root,
}: Awaited<ReturnType<typeof mountDetail>>) {
  root.querySelector('moz-segmented-control')?.dispatchEvent(
    new CustomEvent('moz-segmented-control:change', {
      detail: { value: 'activity' },
    }),
  );
  await el.updateComplete;
  return { el, root };
}

const range = (from: number, to: number) =>
  Array.from({ length: to - from + 1 }, (_, i) => from + i);

function submitReply(root: ShadowRoot) {
  root.querySelector<HTMLFormElement>('form.reply')?.requestSubmit();
}

async function typeReply(el: VersionDetail, root: ShadowRoot, text: string) {
  const input = root.querySelector('.reply moz-input-text') as HTMLElement & {
    value: string;
  };
  input.value = text;
  input.dispatchEvent(new Event('input'));
  await el.updateComplete;
  return input;
}

describe('version-detail', () => {
  it('renders the version details and submission log', async () => {
    const updates = [1, 2, 3, 4, 5].map((n) => ({
      ...update,
      id: String(n),
      title: `Update ${n}`,
    }));
    const { root } = await mountDetail(version, updates);

    const text = root.querySelector('.version-content')?.textContent ?? '';
    expect(text).toContain('Fixed bugs.');
    expect(text).toContain('Run npm build.');
    expect(
      root.querySelector('a[href="/source.zip"]')?.textContent?.trim(),
    ).toBe('Download source');

    // Only the 3 most recent show.
    const steps = [
      ...root.querySelectorAll('.submission-log .timeline li'),
    ].map((li) => li.textContent);
    expect(steps).toHaveLength(3);
    expect(steps[0]).toContain('Update 1');
    expect(steps[2]).toContain('Update 3');
  });

  it('shows an error page when the version fails to load', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response('{}', { status: 404 })),
    );
    queryClient.setQueryDefaults(queryKeys.version('ad-blocker', 404), {
      retry: false,
    });
    const { el } = await mountDetail(null);
    await vi.waitFor(async () => {
      await el.updateComplete;
      expect(el.shadowRoot?.querySelector('error-page')?.code).toBe(404);
    });
  });

  it('sends a developer reply', async () => {
    replyToVersion.mockClear();
    const { el, root } = await openActivity(await mountDetail(version, []));

    const send = root.querySelector<HTMLElement>('.reply moz-button');
    expect(send?.hasAttribute('disabled')).toBe(true);

    const input = await typeReply(el, root, '  Thanks!  ');
    expect(send?.hasAttribute('disabled')).toBe(false);

    submitReply(root);
    await vi.waitFor(() =>
      expect(replyToVersion).toHaveBeenCalledWith('ad-blocker', 7, 'Thanks!'),
    );
    // The field clears once the reply is sent.
    await vi.waitFor(async () => {
      await el.updateComplete;
      expect(input.value).toBe('');
    });
  });

  it('scrolls the activity list to the newest entry after replying', async () => {
    const { el, root } = await openActivity(
      await mountDetail(version, [update]),
    );
    const list = root.querySelector('app-infinite-list');
    if (!list) throw new Error('activity list not rendered');
    const scrollToStart = vi.spyOn(list, 'scrollToStart');

    await typeReply(el, root, 'Thanks!');
    submitReply(root);

    await vi.waitFor(() => expect(scrollToStart).toHaveBeenCalled());
  });

  it('shows each loaded activity page in the infinite list', async () => {
    const entries = range(1, 25).map((n) => ({ ...update, id: String(n) }));
    const page1 = { items: entries.slice(0, 20), total: 25 };
    const { el, root } = await openActivity(
      await mountDetail(version, page1.items, page1.total),
    );

    const list = root.querySelector('app-infinite-list');
    const shown = async () => {
      await el.updateComplete;
      await list?.updateComplete;
      return list?.shadowRoot?.querySelectorAll('chat-card').length ?? 0;
    };
    expect(await shown()).toBe(20);
    expect(list?.hasMore).toBe(true);

    queryClient.setQueryData(['activity', 'infinite', 'ad-blocker', 7], {
      pages: [page1, { items: entries.slice(20), total: 25 }],
      pageParams: [1, 2],
    });
    await vi.waitFor(async () => expect(await shown()).toBe(25));
    expect(list?.hasMore).toBe(false);
  });
});
