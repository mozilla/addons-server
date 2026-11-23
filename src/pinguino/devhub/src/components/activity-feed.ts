import { css, html, LitElement } from 'lit';
import { customElement, property } from 'lit/decorators.js';
import { ACTIVITY_PAGE_SIZE, activityQuery, type Update } from '../data';
import { pageHref } from '../navigation';
import './update-card';

@customElement('activity-feed')
export class ActivityFeed extends LitElement {
  @property() slug = '';
  @property({ type: Number }) page = 1;

  #activity = activityQuery(
    this,
    () => this.slug,
    () => this.page,
  );

  static styles = css`
    :host {
      display: block;
    }
    /* The single gap owner inside the card, matching the versions tab so the
     * two sit identically in their shell. */
    .main-content {
      display: flex;
      flex-direction: column;
      gap: var(--space-xlarge);
    }
    .pager {
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: var(--space-small);
    }
    .count {
      margin: 0;
      font-size: 0.85rem;
      color: var(--text-color-deemphasized, GrayText);
    }
    .items {
      display: flex;
      flex-direction: column;
      gap: var(--space-medium);
    }
    .empty,
    .error {
      padding: var(--space-xxlarge) var(--space-large);
      text-align: center;
      color: var(--text-color-deemphasized, GrayText);
      background-color: var(--background-color-canvas);
      border-radius: var(--border-radius-medium);
    }
  `;

  #items(items: Update[]) {
    if (items.length === 0) {
      return html`<div class="empty">No activity yet.</div>`;
    }
    return html`
      <div class="items">
        ${items.map((item) => html`<update-card .item=${item}></update-card>`)}
      </div>
    `;
  }

  // moz-pagination renders the control and nothing else, so the running tally
  // under it is ours.
  #resultCount(total: number) {
    const from = (this.page - 1) * ACTIVITY_PAGE_SIZE + 1;
    const to = Math.min(this.page * ACTIVITY_PAGE_SIZE, total);
    return html`<p class="count">Results ${from}–${to} of ${total}</p>`;
  }

  render() {
    const { data, isPending, isError } = this.#activity();
    return html`
      <moz-card appearance="outline" spacing="spacious">
        <div class="main-content">
          <moz-page-header
            heading="Activity &amp; Notification"
            description="Review outcomes and other events for this add-on."
          ></moz-page-header>
          ${
            isError
              ? html`<div class="error">Couldn't load activity. Try again.</div>`
              : isPending || !data
                ? html`<div class="empty">Loading activity…</div>`
                : html`
                  ${this.#items(data.items)}
                  <div class="pager">
                    <moz-pagination
                      .page=${this.page}
                      .total=${data.total}
                      .pageSize=${ACTIVITY_PAGE_SIZE}
                      .hrefForPage=${(page: number) => pageHref(page)}
                      max-slots="9"
                      label="Activity pages"
                    ></moz-pagination>
                    ${this.#resultCount(data.total)}
                  </div>
                `
          }
        </div>
      </moz-card>
    `;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'activity-feed': ActivityFeed;
  }
}
