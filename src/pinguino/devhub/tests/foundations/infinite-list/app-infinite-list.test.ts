import { html, type LitElement } from 'lit';
import { describe, expect, it, vi } from 'vitest';
import type { AppInfiniteList } from '../../../src/foundations/infinite-list';
import '../../../src/foundations/infinite-list';
import { mount } from '../../helpers/fixture';

const items = Array.from({ length: 40 }, (_, i) => `item ${i}`);

function list(props: Partial<AppInfiniteList<string>> = {}) {
  return mount<AppInfiniteList<string>>('app-infinite-list', {
    items,
    renderItem: (item: string) => html`<span class="item">${item}</span>`,
    ...props,
  });
}

function showUpTo(el: AppInfiniteList<string>, last: number) {
  const event = new Event('visibilityChanged');
  (event as Event & { last: number }).last = last;
  el.shadowRoot?.querySelector('lit-virtualizer')?.dispatchEvent(event);
}

function onLoadMore(el: AppInfiniteList<string>) {
  const listener = vi.fn();
  el.addEventListener('load-more', listener);
  return listener;
}

describe('app-infinite-list', () => {
  it('renders initial items, asking for more once last rows come into view', async () => {
    const el = await list({
      items: items.slice(0, 20),
      hasMore: true,
      threshold: 5,
    });
    const rendered = () => el.shadowRoot?.querySelectorAll('.row > .item');
    expect(rendered()).toHaveLength(20);
    expect(rendered()?.[3]?.textContent).toBe('item 3');

    const loadMore = onLoadMore(el);

    showUpTo(el, 10);
    expect(loadMore).not.toHaveBeenCalled();

    // Within threshold, loads more.
    showUpTo(el, 15);
    expect(loadMore).toHaveBeenCalledTimes(1);

    // The owner appends the next page.
    el.items = items;
    await el.updateComplete;
    await el.shadowRoot?.querySelector<LitElement>('lit-virtualizer')
      ?.updateComplete;
    expect(rendered()).toHaveLength(40);
  });

  it("doesn't ask for more when there's nothing left or a load is running", async () => {
    const done = await list({ hasMore: false });
    const busy = await list({ hasMore: true, loading: true });

    const doneDispatch = vi.spyOn(done, 'dispatchEvent');
    const busyDispatch = vi.spyOn(busy, 'dispatchEvent');

    showUpTo(done, 19);
    showUpTo(busy, 19);

    expect(doneDispatch).not.toHaveBeenCalled();
    expect(busyDispatch).not.toHaveBeenCalled();
  });

  it('works when wheel is inverted', async () => {
    const el = await list({ inverted: true, hasMore: true });
    const scroller = el.shadowRoot?.querySelector(
      'lit-virtualizer',
    ) as HTMLElement;
    scroller.scrollTop = 500;
    const event = new WheelEvent('wheel', { deltaY: 100, cancelable: true });
    scroller.dispatchEvent(event);

    // Scrolling up still fetches.
    const loadMore = onLoadMore(el);
    const up = new WheelEvent('wheel', { deltaY: -100, cancelable: true });
    scroller.dispatchEvent(up);
    expect(scroller.scrollTop).toBe(500);
    showUpTo(el, 39);
    expect(loadMore).toHaveBeenCalledTimes(1);
  });
});
