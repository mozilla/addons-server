import { css, html, LitElement, nothing } from 'lit';
import { customElement, property } from 'lit/decorators.js';
import { classMap } from 'lit/directives/class-map.js';
import { BASE } from '../../base';
import {
  ADDON_STATUS,
  type Addon,
  type AddonVisibility,
  formatDate,
  updateAddon,
  type Version,
  VISIBILITY,
  versionsQuery,
} from '../../data';
import '../../foundations/badges';

const LABELS = ['Version', 'Status', 'Distribution', 'Visibility', 'Date'];

const VISIBILITY_DESCRIPTION: Record<AddonVisibility, string> = {
  visible:
    'Visible: Visible to everyone on https://addons.mozilla.org and included in search results and product pages.',
  invisible:
    "Won't be included in search results, and its product page will indicate you disabled it. New version submissions for product won't be accepted in this state.",
};

@customElement('addon-version')
export class AddonVersion extends LitElement {
  @property({ attribute: false }) addon!: Addon;

  #versions = versionsQuery(this, () => this.addon?.slug ?? '');

  static styles = css`
    moz-page-header::part(heading) {
      font-size: var(--font-size-heading-medium);
    }
    .main-content {
      display: flex;
      flex-direction: column;
      gap: var(--space-xlarge);
      padding: var(--space-small);
    }
    .version-section {
      display: flex;
      flex-direction: column;
      padding: var(--space-xlarge);
      gap: var(--space-large);
      border-radius: var(--border-radius-large);
      background-color: var(--background-color-canvas);
    }
    .version-section.current {
      background-color: var(--color-violet-desaturated-10);
    }
    .section-title {
      display: flex;
      align-items: center;
      gap: var(--space-small);
      margin: 0;
      font-size: var(--font-size-small);
      font-weight: var(--font-weight-semibold);
      text-transform: uppercase;
    }
    .version-list {
      display: grid;
      grid-template-columns: repeat(5, minmax(max-content, 1fr)) max-content;
      column-gap: var(--space-medium);
      overflow-x: auto;
    }
    .version-row {
      grid-column: 1 / -1;
      display: grid;
      grid-template-columns: subgrid;
      align-items: center;
      padding: var(--space-xlarge) var(--space-medium);
    }
    .version-row:not(.labels) + .version-row {
      border-top: 1px solid var(--color-gray-20);
    }
    .version-row.labels {
      padding-block: 0 var(--space-small);
      color: var(--color-black-alpha-70);
      font-size: var(--font-size-small);
    }
    .current .version-row:not(.labels) {
      padding-block: 0;
    }
    .version-row.next-listed-version {
      position: relative;
      isolation: isolate;
    }
    .version-row.next-listed-version::before {
      content: '';
      position: absolute;
      z-index: -1;
      inset: var(--space-small) 0;
      border-radius: var(--border-radius-medium);
      background-color: var(--background-color-warning);
      opacity: 50%;
    }
    .version-number {
      font-family: 'Mozilla Headline', var(--font-family);
      font-size: var(--font-size-heading-xlarge);
      font-weight: var(--font-weight-semibold);
    }
    moz-radio-group > moz-radio:first-of-type {
      margin-block-start: var(--space-small);
    }
    .manage-button {
      --button-text-color-ghost: var(--color-violet-50);
    }
  `;

  async #setVisibility(event: Event) {
    const visibility = (event.target as HTMLInputElement)
      .value as AddonVisibility;
    await updateAddon(this.addon.slug, {
      is_disabled: visibility === 'invisible',
    });
  }

  renderVisibility() {
    const visibility = this.addon.visibility;
    return html`
      <visibility-badge visibility=${visibility} bordered>
        <moz-radio-group
          full-width
          label="Listing visibility"
          value=${visibility}
          ?disabled=${this.addon.status === ADDON_STATUS.disabled}
          @change=${this.#setVisibility}
        >
          ${(['visible', 'invisible'] as const).map(
            (value) => html`<moz-radio
              value=${value}
              label=${VISIBILITY[value].label}
              description=${VISIBILITY_DESCRIPTION[value]}
            ></moz-radio>`,
          )}
        </moz-radio-group>
      </visibility-badge>
    `;
  }

  get #continueUrl() {
    return `${BASE}/addon/${this.addon.slug}/submit/details`;
  }

  renderIncompleteMessage() {
    return html`
      <moz-message-bar
        type="warning"
        heading="Incomplete listing"
        dismissable
      >
        This add-on is missing some required information before it can be submitted for publication.
        <moz-button variant="muted" slot="actions" href=${this.#continueUrl}
          >Continue uploading</moz-button
        >
      </moz-message-bar>
    `;
  }

  renderVersion(
    version: Version,
    { nextListed = false, showVisibility = false } = {},
  ) {
    const incompleteVersion = this.addon.status === ADDON_STATUS.incomplete;
    return html`
      <div
        class=${classMap({
          'version-row': true,
          'next-listed-version': nextListed,
        })}
      >
        <div class="version-number">${version.version}</div>
        <div>
          <version-badge
            status=${version.file.status}
            ?user-disabled=${version.is_disabled}
            .reviewed=${version.reviewed}
          ></version-badge>
        </div>
        <div>
          <distribution-badge
            distribution=${version.channel ?? 'listed'}
          ></distribution-badge>
        </div>
        <div>${showVisibility ? this.renderVisibility() : '—'}</div>
        <div class="date">${formatDate(version.file.created)}</div>
        <moz-button
          class="manage-button"
          variant="ghost"
          href=${incompleteVersion ? this.#continueUrl : version.edit_url}
          >${incompleteVersion ? 'Continue Uploading' : 'Manage version'}</moz-button
        >
      </div>
    `;
  }

  renderSection(title: string, rows: unknown, { current = false } = {}) {
    return html`
      <div
        gap="large"
        class=${classMap({ 'version-section': true, current })}
      >
        <h3 class="section-title">${title}</h3>
        <div class="version-list">
          <div class="version-row labels">
            ${LABELS.map((label) => html`<div>${label}</div>`)}
          </div>
          ${rows}
        </div>
      </div>
    `;
  }

  getNextListed(currentVersion: Version, versions: Version[]) {
    for (const version of versions) {
      if (
        version.channel === 'listed' &&
        version.file.status === 'unreviewed' &&
        version.id > currentVersion.id &&
        !version.is_disabled
      ) {
        return version.id;
      }
    }
  }

  render() {
    const versions = this.#versions().data;
    if (!versions) return nothing;
    const current = this.addon.currentVersion;
    const otherVersions = versions.filter(
      (version) => version.id !== current?.id,
    );
    let nextListedId: number | undefined;
    if (current) {
      nextListedId = this.getNextListed(current, otherVersions);
    }
    return html`
      <moz-card>
        <div gap="xlarge" class="main-content">
          <moz-page-header
            heading="Version"
            description="See all your versions at once and easily manage them."
          >
            <moz-button
              slot="actions"
              variant="primary"
              icon-start="add"
              href="${BASE}/addon/${this.addon.slug}/versions/submit/distribution"
              >Upload a new version</moz-button
            >
          </moz-page-header>

          ${
            this.addon.status === ADDON_STATUS.incomplete
              ? this.renderIncompleteMessage()
              : nothing
          }
          ${
            current
              ? this.renderSection(
                  'Listed Version',
                  this.renderVersion(current, { showVisibility: true }),
                  { current: true },
                )
              : nothing
          }
          ${
            otherVersions.length
              ? this.renderSection(
                  'Other versions',
                  otherVersions.map((version) =>
                    this.renderVersion(version, {
                      nextListed: version.id === nextListedId,
                    }),
                  ),
                )
              : nothing
          }
        </div>
      </moz-card>
    `;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'addon-version': AddonVersion;
  }
}
