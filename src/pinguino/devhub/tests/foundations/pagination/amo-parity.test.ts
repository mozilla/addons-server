import '@mozilla/lit-web-components/components/moz-pagination';
import type { MozPagination } from '@mozilla/lit-web-components';
import { describe, expect, it } from 'vitest';
import { mount } from '../../helpers/fixture';
import expected from './amo-ranges.json';

// Generated from olympia.amo.templatetags.jinja_helpers.PaginationRenderer.range()
// so the devhub can't silently drift from the server-rendered paginator while
// both exist. moz-pagination counts the pinned first and last page within
// max-slots, where AMO adds them outside its window — 9 here is what makes the
// two agree, so this is also what pins activity-feed's max-slots.
const MAX_SLOTS = 9;

async function numbers(page: number, totalPages: number): Promise<number[]> {
  const el = await mount<MozPagination>('moz-pagination', {
    page,
    totalPages,
    maxSlots: MAX_SLOTS,
  });
  const slots = el.shadowRoot?.querySelectorAll('li.number') ?? [];
  return [...slots].map((li) =>
    Number(li.textContent?.trim().match(/\d+$/)?.[0]),
  );
}

describe('moz-pagination matches AMO for every page of several run lengths', () => {
  it('agrees on all generated cases', async () => {
    const actual: Record<string, number[]> = {};
    for (const key of Object.keys(expected)) {
      const [page, total] = key.split('/').map(Number);
      // A single page renders nothing at all, so there is no run to compare.
      actual[key] = total > 1 ? await numbers(page, total) : [1];
    }
    // AMO's fixture lists only its window; the pinned first and last pages sit
    // outside it, so add them back before comparing to what we render.
    const pinned = Object.fromEntries(
      Object.entries(expected as Record<string, number[]>).map(
        ([key, pages]) => {
          const total = Number(key.split('/')[1]);
          return [
            key,
            [
              ...(pages.includes(1) ? [] : [1]),
              ...pages,
              ...(pages.includes(total) ? [] : [total]),
            ],
          ];
        },
      ),
    );
    expect(actual).toEqual(pinned);
  });
});
