import { describe, expect, it } from 'vitest';
import { paginationRange } from '../../../src/foundations/pagination/pagination-range';
import expected from './amo-ranges.json';

// Generated from olympia.amo.templatetags.jinja_helpers.PaginationRenderer.range()
// so the port can't silently drift from the server-rendered paginator.
describe('paginationRange matches AMO for every page of several run lengths', () => {
  it('agrees on all generated cases', () => {
    const actual: Record<string, number[]> = {};
    for (const key of Object.keys(expected)) {
      const [page, total] = key.split('/').map(Number);
      actual[key] = paginationRange(page, total, 10).pages;
    }
    expect(actual).toEqual(expected);
  });
});
