import '@lit-labs/virtualizer';
import type { VisibilityChangedEvent } from '@lit-labs/virtualizer/events.js';
import { css, html, LitElement, nothing } from 'lit';
import { customElement, property, query } from 'lit/decorators.js';

// A virtualized, infinitely scrolling list. It renders only the rows in view
// and fires `load-more` as the reader nears the last loaded row.
// The owner fetches the next page and appends it to `items`.
@customElement('app-infinite-list')
export class AppInfiniteList<T = unknown> extends LitElement {
  @property({ attribute: false }) items: T[] = [];
  @property({ attribute: false }) renderItem: (
    item: T,
    index: number,
  ) => unknown = () => nothing;
  @property({ type: Boolean, attribute: 'has-more' }) hasMore = false;
  @property({ type: Boolean }) loading = false;
  @property({ type: Boolean, reflect: true }) inverted = false;
  @property({ type: Number }) threshold = 5;

  @query('lit-virtualizer') private scroller?: HTMLElement;

  static styles = css`
    :host {
      position: relative;
      display: flex;
      flex-direction: column;
      min-height: 0;
    }
    lit-virtualizer {
      flex: 1;
      min-height: 0;
    }
    :host([inverted]) lit-virtualizer {
      scale: 1 -1;
    }
    .row {
      box-sizing: border-box;
      width: 100%;
      padding-block-end: var(--infinite-list-gap, var(--space-large));
    }
    :host([inverted]) .row > * {
      scale: 1 -1;
    }
  `;

  scrollToStart() {
    this.scroller?.scrollTo({ top: 0 });
  }

  #renderRow = (item: T, index: number) =>
    html`<div class="row">${this.renderItem(item, index)}</div>`;

  #onVisibilityChanged(e: VisibilityChangedEvent) {
    if (
      e.last >= this.items.length - this.threshold &&
      this.hasMore &&
      !this.loading
    ) {
      this.dispatchEvent(new Event('load-more'));
    }
  }

  #onInvert = (e: WheelEvent) => {
    e.preventDefault();
    (e.currentTarget as HTMLElement).scrollTop -= e.deltaY;
  };

  render() {
    return html`
      <lit-virtualizer
        scroller
        .items=${this.items}
        .renderItem=${this.#renderRow}
        @wheel=${this.inverted ? this.#onInvert : nothing}
        @visibilityChanged=${this.#onVisibilityChanged}
      ></lit-virtualizer>
    `;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'app-infinite-list': AppInfiniteList;
  }
}
