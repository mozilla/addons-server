import '@lit-labs/virtualizer';
import type { VisibilityChangedEvent } from '@lit-labs/virtualizer/events.js';
import type { IconName } from '@mozilla/lit-web-components';
import { css, html, LitElement } from 'lit';
import { customElement } from 'lit/decorators.js';
import '../components/addon-card';
import '../components/submit-card';
import '../components/update-card';
import type { ActivityPage, AddonKind, AddonsQuery, Update } from '../data';
import { activityInfiniteQuery, addonsQuery, profileQuery } from '../data';
import { setPageTitle } from '../page-title';

// Threshold for loading more rows once the reader is close, so they're ready beforehand
const LOAD_MORE_THRESHOLD = 5;

interface Group {
  title: string;
  icon: IconName;
  submitLabel: string;
}

const GROUPS: Record<AddonKind, Group> = {
  extension: {
    title: 'Extensions',
    icon: 'extension',
    submitLabel: 'Submit new extension',
  },
  theme: {
    title: 'Themes',
    icon: 'themes',
    submitLabel: 'Submit new theme',
  },
};

@customElement('devhub-home')
export class DevhubHome extends LitElement {
  #profile = profileQuery(this);
  #extensions = addonsQuery(this, 'extension');
  #themes = addonsQuery(this, 'theme');
  #updates = activityInfiniteQuery(this);

  connectedCallback() {
    super.connectedCallback();
    setPageTitle();
  }

  static styles = css`
    :host {
      display: block;
    }
    moz-page-header {
      display: block;
      margin-block: var(--space-xxlarge);
    }
    .section {
      padding: var(--space-xlarge);
      background-color: var(--background-color-box);
      border-radius: var(--border-radius-medium);
    }
    .count {
      display: flex;
      gap: var(--space-small);
      align-items: center;
      margin: 0 0 var(--space-medium);
      font-size: 0.85rem;
      color: var(--text-color-deemphasized, GrayText);
    }
    .feed-column {
      height: 1030px;
    }
    .feed {
      height: 100%;
      box-sizing: border-box;
    }
    .feed-scroller {
      flex: 1;
      min-height: 0;
    }
    .feed-scroller update-card {
      display: block;
      box-sizing: border-box;
      width: 100%;
      margin-block-end: var(--space-large);
    }
    .loading-more {
      margin: 0;
      text-align: center;
      color: var(--text-color-deemphasized, GrayText);
    }
    .empty-updates {
      display: flex;
      flex: 1;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      gap: var(--space-medium);
      padding: var(--space-xxlarge) var(--space-large);
      text-align: center;
      color: var(--text-color-deemphasized, GrayText);

      > * {
        margin: 0;
      }

      moz-illustration {
        width: 110px;
        rotate: 30deg;
        margin: 30px;
      }
    }
  `;

  render() {
    const name = this.#profile().data?.name;
    const heading = name
      ? `Welcome to the Developer Hub, ${name}`
      : 'Welcome to the Developer Hub.';
    return html`
      <moz-page-header
        heading=${heading}
        description="Manage your Firefox add-ons, track reviews, and publish updates."
      ></moz-page-header>

      <app-grid columns-md="1" gap="xlarge">
        <div style="grid-column: span 7">
          <app-stack gap="xlarge">
            ${this.#group('extension', this.#extensions)}
            ${this.#group('theme', this.#themes)}
          </app-stack>
        </div>
        <div class="feed-column" style="grid-column: span 5">
          ${this.#feed(this.#updates().data?.pages ?? [])}
        </div>
      </app-grid>
    `;
  }

  // Each section owns its request, so one kind failing or still loading leaves
  // the other readable.
  #group(kind: AddonKind, query: AddonsQuery) {
    const { title, icon, submitLabel } = GROUPS[kind];
    const { data, isError, isPending } = query();

    if (isError) {
      return html`
        <section class="section">
          <div class="count">
            <span>We couldn't load your ${title.toLowerCase()}.</span>
            <moz-button size="small" @click=${() => query.refetch()}>
              Retry
            </moz-button>
          </div>
        </section>
      `;
    }
    if (isPending) {
      return html`
        <section class="section">
          <p class="count">Loading your ${title.toLowerCase()}…</p>
        </section>
      `;
    }

    const items = data.results;
    return html`
      <section class="section">
        <p class="count">
          <moz-icon name=${icon} color="accent-primary-desaturated"></moz-icon>
          ${data.count} ${title}
        </p>
        ${
          items.length > 0
            ? html`
          <app-grid columns="2" columns-md="2" columns-sm="1" gap="large">
            ${items.map((a) => html`<addon-card .addon=${a}></addon-card>`)}
            <submit-card label=${submitLabel}></submit-card>
          </app-grid>
        `
            : html`
          <app-grid columns="1" gap="large">
            <submit-card label=${submitLabel}></submit-card>
          </app-grid>
        `
        }
      </section>
    `;
  }

  // Pull the next page in as the reader nears the end of the loaded rows.
  #loadMoreIfNeeded(lastVisible: number, loaded: number) {
    const feed = this.#updates();
    if (
      lastVisible >= loaded - LOAD_MORE_THRESHOLD &&
      feed.hasNextPage &&
      !feed.isFetchingNextPage
    ) {
      this.#updates.fetchNextPage();
    }
  }

  #feed(pages: ActivityPage[]) {
    const updates = pages.flatMap((p) => p.items);
    if (updates.length === 0) {
      return html`
        <app-stack gap="medium" class="section feed">
          <div class="empty-updates">
            <moz-illustration name="pic-puzzle"></moz-illustration>
            <h3>All quiet for now</h3>
            Updates about your add-ons will land here.
          </div>
        </app-stack>
      `;
    }
    // The server's running total across all pages, not just the rows loaded so
    // far; every page carries it, so read it from the latest.
    const total = pages.at(-1)?.total ?? updates.length;
    return html`
      <app-stack gap="medium" class="section feed" style="gap: 0">
        <p class="count">
          ${total} Updates
        </p>
        <lit-virtualizer
          scroller
          class="feed-scroller"
          .items=${updates}
          .renderItem=${(u: Update) =>
            html`<update-card .item=${u}></update-card>`}
          @visibilityChanged=${(e: VisibilityChangedEvent) =>
            this.#loadMoreIfNeeded(e.last, updates.length)}
        ></lit-virtualizer>
        ${
          this.#updates().isFetchingNextPage
            ? html`<p class="loading-more">Loading more…</p>`
            : undefined
        }
      </app-stack>
    `;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'devhub-home': DevhubHome;
  }
}
