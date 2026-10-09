import { css, html, LitElement, type TemplateResult } from 'lit';
import { customElement, property } from 'lit/decorators.js';
import type { Addon } from '../data';

// The four listing flags, shown as (read-only) checkboxes with help text so the
// view mirrors the edit form. `key` indexes Addon['flags'].
const FLAGS = [
  {
    key: 'experimental',
    label: 'Experimental',
    description:
      'If your add-on is experimental or otherwise not ready for general use. It will be listed but not featured.',
  },
  {
    key: 'requiresPayment',
    label:
      'This add-on requires payment, non-free services or software, or additional hardware',
    description:
      'Disclose any costs so reviewers and users know what to expect.',
  },
  {
    key: 'hasEula',
    label: 'This add-on has an End-User License Agreement',
    description:
      'The EULA must be accepted before installation. Only relevant for listed add-ons.',
  },
  {
    key: 'hasPrivacyPolicy',
    label: 'This add-on has a Privacy Policy',
    description:
      "If your add-on collects data, a privacy policy is required explaining what's sent and how it's used. Only relevant for listed add-ons.",
  },
] as const;

const SECTIONS = [
  { id: 'listing-details', label: 'Listing details', icon: 'settings' },
  { id: 'graphic-assets', label: 'Images', icon: 'canvas' },
  { id: 'authors', label: 'Authors', icon: 'users' },
  { id: 'technical-details', label: 'Technical details', icon: 'layer' },
] as const;

@customElement('addon-listing')
export class AddonListing extends LitElement {
  @property({ attribute: false }) addon!: Addon;

  static styles = css`
    :host {
      display: block;
    }
    .layout {
      display: grid;
      grid-template-columns: 220px 1fr;
      gap: var(--space-xlarge);
      align-items: start;
    }
    moz-page-nav {
      position: sticky;
      top: var(--space-medium);
    }
    .cards {
      display: flex;
      flex-direction: column;
      gap: var(--space-large);
      min-width: 0;
    }
    .card-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: var(--space-small);
      width: 100%;
      margin-bottom: var(--space-xlarge);
    }
    .card-head h2 {
      margin: 0;
      font-size: var(--font-size-heading-medium);
    }
    .card-head .sub {
      margin: var(--space-xxsmall) 0 0;
      color: var(--text-color-deemphasized, GrayText);
    }
    dl {
      margin: 0;
      display: flex;
      flex-direction: column;
      gap: var(--space-xlarge);
    }
    .field dt {
      color: var(--text-color-deemphasized, GrayText);
      margin-bottom: var(--space-small);
    }
    .field dd {
      margin: 0;
    }
    .muted {
      color: var(--text-color-deemphasized, GrayText);
    }
    .categories {
      display: flex;
      flex-wrap: wrap;
      gap: var(--space-xsmall);
    }
    .flags {
      display: flex;
      flex-direction: column;
      gap: var(--space-medium);
      margin-top: var(--space-xxlarge);
    }
    .authors {
      display: flex;
      flex-direction: column;
      gap: var(--space-large);
    }
    .author {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: var(--space-medium);
    }
    .asset + .asset {
      margin-top: var(--space-large);
    }
    .asset .label {
      font-weight: 600;
      margin: 0 0 var(--space-xxsmall);
    }
    .asset .help {
      color: var(--text-color-deemphasized, GrayText);
      margin: 0 0 var(--space-small);
    }
    .icon-sizes {
      display: flex;
      gap: var(--space-medium);
      align-items: flex-end;
    }
    .icon-box {
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: var(--space-xxsmall);
      color: var(--text-color-deemphasized, GrayText);
    }
    .icon-box .frame {
      display: grid;
      place-items: center;
      border: 1px solid #e4d7fc;
      border-radius: var(--border-radius-small, 4px);
    }
    .shots {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
      gap: var(--space-medium);
    }
    .shots img {
      width: 100%;
      border-radius: var(--border-radius-medium, 8px);
    }
    @media (max-width: 760px) {
      .layout {
        grid-template-columns: 1fr;
      }
      moz-page-nav {
        position: static;
      }
      .author {
        grid-template-columns: 1fr;
      }
    }
  `;

  // moz-page-nav's scrollspy highlights the section in view, but it leaves the
  // actual scroll to native hash navigation — which can't reach our shadow-DOM
  // cards. Resolve the target in our own root and scroll it instead.
  #onNav = (e: Event) => {
    const id = (e as CustomEvent<{ value?: string }>).detail.value;
    if (id) {
      this.renderRoot
        .querySelector(`#${id}`)
        ?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  };

  #cardHead(title: string, subtitle: string) {
    return html`<div slot="heading" class="card-head">
      <div>
        <h2>${title}</h2>
        <p class="sub">${subtitle}</p>
      </div>
      <moz-button size="small">Edit</moz-button>
    </div>`;
  }

  // Always renders the label; falls back to a muted dash so the section keeps
  // the design's shape even when a value is absent.
  #row(label: string, value: unknown): TemplateResult {
    const empty = value == null || value === '';
    return html`<div class="field">
      <dt>${label}</dt>
      <dd>${empty ? html`<span class="muted">—</span>` : value}</dd>
    </div>`;
  }

  #link(url: string | undefined) {
    return url
      ? html`<a href=${url} target="_blank" rel="noopener">${url}</a>`
      : null;
  }

  #iconBox(px: number) {
    const a = this.addon;
    const inner = a.iconUrl
      ? html`<img
          src=${a.iconUrl}
          alt=""
          style="width:${px}px;height:${px}px;border-radius:4px"
        />`
      : undefined;
    return html`<div class="icon-box">
      <div class="frame" style="width:${px + 16}px;height:${px + 16}px">
        ${inner}
      </div>
      ${px}×${px}px
    </div>`;
  }

  render() {
    const a = this.addon;
    const flags = a.flags ?? {};
    return html`
      <div class="layout">
        <moz-page-nav
          scrollspy
          @moz-page-nav:change=${this.#onNav}
          label="Listing sections"
        >
          <h3 slot="heading" style="margin:0">Details</h3>
          ${SECTIONS.map(
            (s) => html`<moz-page-nav-button
              href="#${s.id}"
              icon-start=${s.icon}
              >${s.label}</moz-page-nav-button
            >`,
          )}
        </moz-page-nav>

        <div class="cards">
          <moz-card appearance="outline" spacing="spacious" id="listing-details">
            ${this.#cardHead(
              'Listing Details',
              'Describe your listing, categories, and promotional assets on AMO.',
            )}
            <dl>
              ${this.#row('Add-on name', a.name)}
              ${this.#row('Add-on URL', this.#link(a.listingUrl))}
              ${this.#row('Homepage of the add-on', this.#link(a.homepageUrl))}
              ${this.#row('Website', this.#link(a.websiteUrl))}
              ${this.#row('Support Email', a.supportEmail)}
              ${this.#row('Summary', a.summary)}
              ${this.#row('Description', a.description)}
              ${this.#row(
                'Categories',
                a.categories?.length
                  ? html`<div class="categories">
                      ${a.categories.map((c) => html`<moz-status-badge>${c}</moz-status-badge>`)}
                    </div>`
                  : null,
              )}
            </dl>
            <div class="flags">
              ${FLAGS.map(
                (f) => html`<moz-checkbox
                  disabled
                  ?checked=${Boolean(flags[f.key])}
                  label=${f.label}
                  description=${f.description}
                ></moz-checkbox>`,
              )}
            </div>
          </moz-card>

          <moz-card appearance="outline" spacing="spacious" id="graphic-assets">
            ${this.#cardHead(
              'Graphic assets',
              'The icon and screenshots shown on your listing.',
            )}
            <div class="asset">
              <p class="label">Add-on icon</p>
              <p class="help">
                Upload a PNG or JPG. Icons larger than 128×128px are resized and
                scaled to each size below.
              </p>
              <div class="icon-sizes">
                ${[32, 64, 128].map((px) => this.#iconBox(px))}
              </div>
            </div>
            <div class="asset">
              <p class="label">Screenshots</p>
              <p class="help">
                We support PNG and JPG, but PNG is best. Screenshots should be up to 2400×1800 pixels. Adding screenshots to your product page really boosts the chances people will install it.
              </p>
              ${
                a.screenshots?.length
                  ? html`<div class="shots">
                      ${a.screenshots.map(
                        (s) =>
                          html`<img src=${s.src} alt=${s.caption ?? ''} />`,
                      )}
                    </div>`
                  : html`<p class="muted">No screenshots uploaded yet.</p>`
              }
            </div>
          </moz-card>

          <moz-card appearance="outline" spacing="spacious" id="authors">
            ${this.#cardHead(
              'Authors',
              'Developers with permission to manage this add-on.',
            )}
            <!-- TODO: All the API only gives us the user display_name? -->
            ${
              a.authors?.length
                ? html`<div class="authors">
                    ${a.authors.map((au) => {
                      const role = au.role ?? 'Developer';
                      return html`<div class="author">
                        ${this.#row(role, au.name)}
                        ${this.#row(`${role} email`, au.email)}
                      </div>`;
                    })}
                  </div>`
                : html`<p class="muted">No authors listed.</p>`
            }
          </moz-card>

          <moz-card appearance="outline" spacing="spacious" id="technical-details">
            ${this.#cardHead(
              'Technical Details',
              'Developer notes and metadata for this add-on.',
            )}
            <dl>
              ${this.#row('Developer comments', a.developerComments)}
              ${this.#row('UUID', a.uuid)}
              ${this.#row('Whiteboard', a.whiteboard)}
            </dl>
          </moz-card>
        </div>
      </div>
    `;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'addon-listing': AddonListing;
  }
}
