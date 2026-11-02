import { describe, expect, it } from 'vitest';
import { paginationRange } from '../../../src/foundations/pagination/pagination-range';

// Expected values come from AMO's PaginationRenderer.range(), which this ports;
// the new pager has to show the same numbers as the page it replaces.
describe('paginationRange', () => {
  it('shows every page when they all fit', () => {
    const { pages, dottedLower, dottedUpper } = paginationRange(1, 5, 10);
    expect(pages).toEqual([1, 2, 3, 4, 5]);
    expect(dottedLower).toBe(false);
    expect(dottedUpper).toBe(false);
  });

  it('truncates only the far end near the start', () => {
    const { pages, dottedLower, dottedUpper } = paginationRange(2, 20, 10);
    expect(pages).toEqual([1, 2, 3, 4, 5, 6, 7, 8]);
    expect(dottedLower).toBe(false);
    expect(dottedUpper).toBe(true);
  });

  it('truncates only the near end at the finish', () => {
    const { pages, dottedLower, dottedUpper } = paginationRange(20, 20, 10);
    expect(pages).toEqual([13, 14, 15, 16, 17, 18, 19, 20]);
    expect(dottedLower).toBe(true);
    expect(dottedUpper).toBe(false);
  });

  it('centres the window and truncates both ends in the middle', () => {
    const { pages, dottedLower, dottedUpper } = paginationRange(10, 20, 10);
    expect(pages).toEqual([7, 8, 9, 10, 11, 12, 13]);
    expect(dottedLower).toBe(true);
    expect(dottedUpper).toBe(true);
  });

  it('includes the current page for every page of a long run', () => {
    for (let page = 1; page <= 20; page++) {
      expect(paginationRange(page, 20, 10).pages).toContain(page);
    }
  });

  it('never emits a page outside 1..numPages', () => {
    for (let page = 1; page <= 20; page++) {
      for (const n of paginationRange(page, 20, 10).pages) {
        expect(n).toBeGreaterThanOrEqual(1);
        expect(n).toBeLessThanOrEqual(20);
      }
    }
  });
});
