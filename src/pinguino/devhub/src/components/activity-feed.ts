import { css, html, LitElement } from 'lit';
import { customElement, property } from 'lit/decorators.js';
import { ACTIVITY_PAGE_SIZE, activityQuery, type Update } from '../data';
import '../foundations/pagination';
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
    .head {
      margin-bottom: var(--space-large);
    }
    .head h2 {
      margin: 0 0 var(--space-xsmall);
      font-size: 1.0625rem;
    }
    .head p {
      margin: 0;
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
    app-pagination {
      margin-top: var(--space-large);
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

  render() {
    const { data, isPending, isError } = this.#activity();
    return html`
      <div class="head">
        <h2>Activity &amp; Notification</h2>
        <p>Review outcomes and other events for this add-on.</p>
      </div>
      ${
        isError
          ? html`<div class="error">Couldn't load activity. Try again.</div>`
          : isPending || !data
            ? html`<div class="empty">Loading activity…</div>`
            : html`
              ${this.#items(data.items)}
              <app-pagination
                .page=${this.page}
                .total=${data.total}
                .pageSize=${ACTIVITY_PAGE_SIZE}
                label="Activity pages"
              ></app-pagination>
            `
      }
    `;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'activity-feed': ActivityFeed;
  }
}
