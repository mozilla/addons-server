import { describe, expect, it } from 'vitest';
import type { AppPagination } from '../../../src/foundations/pagination/app-pagination';
import '../../../src/foundations/pagination';
import { mount } from '../../helpers/fixture';

async function pager(props: Partial<AppPagination>) {
  const el = await mount<AppPagination>('app-pagination', {
    pageSize: 20,
    ...props,
  });
  return el.shadowRoot as ShadowRoot;
}

const labels = (root: ShadowRoot) =>
  [...root.querySelectorAll('ol > li')].map((li) =>
    // The visually-hidden "Page " / "Current page, " prefix carries the context
    // for assistive tech; strip it to assert on what's on screen.
    li.textContent?.replace(/Current page,|Page/g, '').trim(),
  );

describe('app-pagination', () => {
  it('renders nothing when everything fits on one page', async () => {
    const root = await pager({ page: 1, total: 20 });
    expect(root.querySelector('nav')).toBeNull();
  });

  it('always shows both steps, whichever page is current', async () => {
    const first = await pager({ page: 1, total: 60 });
    expect(labels(first)).toEqual(['Prev', '1', '2', '3', 'Next']);

    const last = await pager({ page: 3, total: 60 });
    expect(labels(last)).toEqual(['Prev', '1', '2', '3', 'Next']);
  });

  it('disables the step that has nowhere to go', async () => {
    const first = await pager({ page: 1, total: 60 });
    expect(first.querySelector('[rel="prev"]')?.hasAttribute('disabled')).toBe(
      true,
    );
    expect(first.querySelector('[rel="next"]')?.hasAttribute('disabled')).toBe(
      false,
    );

    const last = await pager({ page: 3, total: 60 });
    expect(last.querySelector('[rel="prev"]')?.hasAttribute('disabled')).toBe(
      false,
    );
    expect(last.querySelector('[rel="next"]')?.hasAttribute('disabled')).toBe(
      true,
    );
  });

  it('disables the current page and leaves the others clickable', async () => {
    const root = await pager({ page: 2, total: 60 });
    const numbers = [...root.querySelectorAll('moz-button:not([rel])')];
    expect(
      numbers.map((b) => [b.textContent?.trim(), b.hasAttribute('disabled')]),
    ).toEqual([
      ['Page 1', false],
      ['Current page, 2', true],
      ['Page 3', false],
    ]);
  });

  it('drops the href on a disabled step so it cannot navigate', async () => {
    const root = await pager({ page: 1, total: 60 });
    expect(root.querySelector('[rel="prev"]')?.hasAttribute('href')).toBe(
      false,
    );
    expect(
      root.querySelector('moz-button[aria-current]')?.hasAttribute('href'),
    ).toBe(false);
  });

  it('pins the first and last page behind ellipses when truncated', async () => {
    const root = await pager({ page: 10, total: 400 });
    expect(labels(root)).toEqual([
      'Prev',
      '1',
      '…',
      '7',
      '8',
      '9',
      '10',
      '11',
      '12',
      '13',
      '…',
      '20',
      'Next',
    ]);
  });

  it('names the current page for assistive tech', async () => {
    const root = await pager({ page: 2, total: 60 });
    const current = root.querySelector('moz-button[aria-current="page"]');
    expect(current?.textContent?.trim()).toBe('Current page, 2');
  });

  it('styles numbers as default buttons and the steps as primary', async () => {
    const root = await pager({ page: 2, total: 60 });
    const variant = (sel: string) =>
      root.querySelector(sel)?.getAttribute('variant');
    expect(variant('moz-button[rel="prev"]')).toBe('primary');
    expect(variant('moz-button[rel="next"]')).toBe('primary');
    expect(variant('moz-button[aria-current="page"]')).toBe('default');
  });

  it('links to each page with a real href that keeps other params', async () => {
    history.replaceState({}, '', '?action=updates&page=2');
    const root = await pager({ page: 2, total: 60 });
    const next = root.querySelector('moz-button[rel="next"]');
    expect(next?.getAttribute('href')).toBe('?action=updates&page=3');
    history.replaceState({}, '', location.pathname);
  });

  it('drives a custom query parameter when asked', async () => {
    history.replaceState({}, '', '');
    const root = await pager({ page: 1, total: 60, param: 'feedPage' });
    expect(
      root.querySelector('moz-button[rel="next"]')?.getAttribute('href'),
    ).toBe('?feedPage=2');
  });

  it('reports the slice of results on show, clamped to the total', async () => {
    const mid = await pager({ page: 2, total: 42 });
    expect(mid.querySelector('.count')?.textContent?.trim()).toBe(
      'Results 21–40 of 42',
    );

    const end = await pager({ page: 3, total: 42 });
    expect(end.querySelector('.count')?.textContent?.trim()).toBe(
      'Results 41–42 of 42',
    );
  });
});
