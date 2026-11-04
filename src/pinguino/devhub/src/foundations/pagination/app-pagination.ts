import { css, html, LitElement, nothing } from 'lit';
import { customElement, property } from 'lit/decorators.js';
import { paginationRange } from './pagination-range';

// Each step is a moz-button with href — a real <a> styled as a button — so a
// page stays bookmarkable and middle-clickable; the router takes the plain
// left-click.
@customElement('app-pagination')
export class AppPagination extends LitElement {
  /** Current page, 1-based. */
  @property({ type: Number }) page = 1;
  /** Total number of items across all pages, not the length of this page. */
  @property({ type: Number }) total = 0;
  @property({ type: Number }) pageSize = 20;
  /** How many numbered slots to show before truncating with an ellipsis. */
  @property({ type: Number }) maxSlots = 10;
  // Named so two paginated lists can share one page.
  @property() param = 'page';
  @property() label = 'Pagination';

  static styles = css`
    :host {
      display: block;
    }
    nav {
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: var(--space-small);
    }
    ol {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: var(--space-xsmall);
      margin: 0;
      padding: 0;
      list-style: none;
    }
    /* Disabled already dims the dead steps; weight is what tells the current
     * page apart from them. */
    moz-button[aria-current]::part(button) {
      font-weight: 600;
    }
    .skip {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 32px;
      color: var(--text-color-deemphasized, GrayText);
    }
    .sr-only {
      position: absolute;
      width: 1px;
      height: 1px;
      overflow: hidden;
      clip-path: inset(50%);
      white-space: nowrap;
    }
    .count {
      margin: 0;
      font-size: 0.85rem;
      color: var(--text-color-deemphasized, GrayText);
    }
  `;

  get #numPages() {
    return Math.max(1, Math.ceil(this.total / this.pageSize));
  }

  // Relative href so other query params on the URL survive paging.
  #href(page: number) {
    const params = new URLSearchParams(location.search);
    params.set(this.param, String(page));
    return `?${params}`;
  }

  // moz-button won't forward aria-current to the inner <a>, so the accessible
  // name carries the context instead. Dropping the href on a disabled step
  // makes moz-button render a <button>, so it's dead rather than just dimmed.
  #step(page: number, text: string, rel?: 'prev' | 'next') {
    const current = !rel && page === this.page;
    const disabled = current || page < 1 || page > this.#numPages;
    const prefix = rel ? '' : current ? 'Current page, ' : 'Page ';
    return html`<li>
      <moz-button
        size="small"
        variant=${rel ? 'primary' : 'default'}
        href=${disabled ? nothing : this.#href(page)}
        rel=${rel ?? nothing}
        ?disabled=${disabled}
        aria-current=${current ? 'page' : nothing}
      >
        ${prefix ? html`<span class="sr-only">${prefix}</span>` : nothing}${text}
      </moz-button>
    </li>`;
  }

  render() {
    const numPages = this.#numPages;
    if (numPages <= 1) return nothing;

    const { pages, dottedLower, dottedUpper } = paginationRange(
      this.page,
      numPages,
      this.maxSlots,
    );
    const from = (this.page - 1) * this.pageSize + 1;
    const to = Math.min(this.page * this.pageSize, this.total);

    return html`
      <nav aria-label=${this.label}>
        <ol>
          ${this.#step(this.page - 1, 'Previous', 'prev')}
          ${
            dottedLower
              ? html`${this.#step(1, '1')}<li class="skip" aria-hidden="true">…</li>`
              : nothing
          }
          ${pages.map((n) => this.#step(n, String(n)))}
          ${
            dottedUpper
              ? html`<li class="skip" aria-hidden="true">…</li>${this.#step(numPages, String(numPages))}`
              : nothing
          }
          ${this.#step(this.page + 1, 'Next', 'next')}
        </ol>
        <p class="count">Results ${from}–${to} of ${this.total}</p>
      </nav>
    `;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'app-pagination': AppPagination;
  }
}
