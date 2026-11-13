import { css, html, LitElement } from 'lit';
import { customElement, property } from 'lit/decorators.js';
import { BASE } from '../../../base';
import '../../../components/activity-feed';
import '../../../components/addon-listing';
import '../../../components/addon-manage-header';
import '../../../components/addon-version/addon-version';
import '../../../components/coming-soon';
import {
  SECTION,
  type SectionId,
} from '../../../components/addon-listing/sections';
import { type Addon, addonQuery } from '../../../data';
import { setPageTitle } from '../../../page-title';

// Each tab is its own URL under <base>/addon/:slug/<tab>, so a tab is linkable
// and survives reload. The bare add-on URL defaults to the listing editor.
const TABS = [
  { value: 'versions', label: 'Versions' },
  { value: 'feed', label: 'Activity & Notification' },
  { value: 'edit', label: 'Listing Details' },
  { value: 'statistics', label: 'Statistics' },
] as const;

type TabValue = (typeof TABS)[number]['value'];
const DEFAULT_TAB: TabValue = 'edit';
const isTab = (v: string): v is TabValue => TABS.some((t) => t.value === v);

@customElement('devhub-addon')
export class DevhubAddon extends LitElement {
  @property() slug = '';
  @property() tab: string = DEFAULT_TAB;
  // Active section within the Listing Details (edit) tab.
  @property() section = '';
  // 1-based page for the Activity & Notification (feed) tab.
  @property({ type: Number }) page = 1;

  #addon = addonQuery(this, () => this.slug);

  updated() {
    setPageTitle([this.#pageTitle, this.#addon().data?.name]);
  }

  get #pageTitle(): string {
    switch (this.#activeTab) {
      case 'edit': {
        // Within the edit tab, use the active section too
        const section = SECTION[this.section as SectionId];
        return `Edit ${section ? section.title : 'Listing details'}`;
      }
      case 'feed':
        return 'Activity & Notification';
      case 'versions':
        return 'Versions';
      default:
        // For not implemented tabs return an empty string so it's just the add-on name.
        return '';
    }
  }

  static styles = css`
    :host {
      display: block;
    }
    moz-segmented-control {
      margin-block: var(--space-large) var(--space-xlarge);
    }
    .stub {
      padding: var(--space-xxlarge) var(--space-large);
      text-align: center;
      color: var(--text-color-deemphasized, GrayText);
      background-color: var(--background-color-box);
      border-radius: var(--border-radius-medium);
    }
  `;

  get #activeTab(): TabValue {
    return isTab(this.tab) ? this.tab : DEFAULT_TAB;
  }

  #selectTab = (e: Event) => {
    const { value } = (e as CustomEvent<{ value: string }>).detail;
    const url = `${BASE}/addon/${this.slug}/${value}`;
    if (location.pathname !== url) {
      history.pushState({}, '', url);
      // Nudge the shell router (it re-renders on popstate) to match the URL.
      dispatchEvent(new PopStateEvent('popstate'));
    }
  };

  #panel(addon: Addon) {
    // Django detail pages we haven't reimplemented yet.
    if (this.tab === 'invitation') {
      return html`<coming-soon></coming-soon>`;
    }
    switch (this.#activeTab) {
      case 'edit':
        return html`<addon-listing
          .addon=${addon}
          .section=${this.section || undefined}
        ></addon-listing>`;
      case 'feed':
        return html`<activity-feed
          .slug=${addon.slug}
          .page=${this.page}
        ></activity-feed>`;
      case 'versions':
        return html`<addon-version
          .addon=${addon}
          .section=${this.section || undefined}
        ></addon-version>`;
      default: {
        return html`<coming-soon></coming-soon>`;
      }
    }
  }

  render() {
    const result = this.#addon();
    if (result.isPending) {
      return html`<p class="stub">Loading…</p>`;
    }
    const a = result.data;
    if (!a) {
      return html`
        <p><a href="${BASE}/">&larr; Back to dashboard</a></p>
        <p class="stub">We couldn't find that add-on.</p>
      `;
    }

    return html`
      <addon-manage-header .addon=${a}></addon-manage-header>

      <moz-segmented-control
        value=${this.#activeTab}
        @moz-segmented-control:change=${this.#selectTab}
        label="Manage sections"
        fill
      >
        ${TABS.map(
          (t) => html`<moz-segmented-control-item
            value=${t.value}
            label=${t.label}
          ></moz-segmented-control-item>`,
        )}
      </moz-segmented-control>

      ${this.#panel(a)}
    `;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'devhub-addon': DevhubAddon;
  }
}
