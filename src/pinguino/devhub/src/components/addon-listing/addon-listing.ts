import { html, LitElement } from 'lit';
import { customElement, property } from 'lit/decorators.js';
import { BASE } from '../../base';
import type { Addon } from '../../data';
// Registering the section cards (side-effect imports) so the shell can render
// them by tag name.
import './authors-card';
import './graphic-assets-card';
import './listing-details-card';
import './technical-details-card';
import { sharedStyles } from './section-card';
import { SECTION, SECTIONS, type SectionId } from './sections';

// Shell for the Listing Details (edit) tab: a section nav plus the one section
// card for the active route. Each card owns its own edit/save state, so leaving
// a section (swapping the child element) drops any unsaved edits for free.
@customElement('addon-listing')
export class AddonListing extends LitElement {
  @property({ attribute: false }) addon!: Addon;
  // Which section (card) to show; each is its own page under the edit tab.
  @property() section: string = SECTIONS[0].id;

  static styles = sharedStyles;

  get #activeSection(): SectionId {
    return this.section in SECTION
      ? (this.section as SectionId)
      : SECTIONS[0].id;
  }

  #activeCard() {
    const a = this.addon;
    switch (this.#activeSection) {
      case 'graphic-assets':
        return html`<graphic-assets-card .addon=${a}></graphic-assets-card>`;
      case 'authors':
        return html`<authors-card .addon=${a}></authors-card>`;
      case 'technical-details':
        return html`<technical-details-card
          .addon=${a}
        ></technical-details-card>`;
      default:
        return html`<listing-details-card
          .addon=${a}
        ></listing-details-card>`;
    }
  }

  render() {
    const a = this.addon;
    return html`
      <div class="layout">
        <moz-page-nav .current=${this.#activeSection} label="Listing sections">
          <h3 slot="heading" style="margin:0">Details</h3>
          ${SECTIONS.map(
            (s) => html`<moz-page-nav-button
              value=${s.id}
              href="${BASE}/addon/${a.slug}/edit/${s.id}"
              icon-start=${s.icon}
              >${s.title}</moz-page-nav-button
            >`,
          )}
        </moz-page-nav>

        <div class="cards">${this.#activeCard()}</div>
      </div>
    `;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'addon-listing': AddonListing;
  }
}
