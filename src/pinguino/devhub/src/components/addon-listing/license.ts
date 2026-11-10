import { css, html, LitElement, nothing } from 'lit';
import { customElement, property } from 'lit/decorators.js';
import { EXTENSION_LICENSES, THEME_LICENSES } from '../../licenses';
import { emit } from '../../utils/helper';

export const CUSTOM_LICENSE = 'other';

export type LicenseFieldKey = 'license' | 'license_name' | 'license_text';

export type LicenseFieldChange = { field: LicenseFieldKey; value: string };

@customElement('license-field')
export class LicenseField extends LitElement {
  @property({ type: Boolean }) theme = false;
  @property() license = '';
  @property({ attribute: 'license-name' }) licenseName = '';
  @property({ attribute: 'license-text' }) licenseText = '';
  @property({ attribute: false }) errors: Partial<
    Record<LicenseFieldKey, string>
  > = {};

  static styles = css`
    :host {
      display: flex;
      flex-direction: column;
      gap: var(--space-medium);
    }
    moz-radio-group::part(legend) {
      padding-bottom: var(--space-small);
    }
    moz-radio-group::part(error) {
      font-size: inherit;
      font-weight: inherit;
    }
    moz-radio::part(label) {
      float: inline-start;
      margin-inline-end: var(--space-small);
    }
    moz-radio::part(description) {
      font-size: inherit;
    }
  `;

  #emit(field: LicenseFieldKey, e: Event) {
    const value = (e.target as HTMLInputElement).value;
    emit(this, 'license-change', { field, value } satisfies LicenseFieldChange);
  }

  render() {
    const licenses = this.theme ? THEME_LICENSES : EXTENSION_LICENSES;
    return html`<moz-radio-group
        label="License"
        name="license"
        full-width
        error=${this.errors.license ?? ''}
        .value=${this.license}
        @change=${(e: Event) => this.#emit('license', e)}
      >
        ${licenses.map(
          (l) =>
            html`<moz-radio value=${l.slug} label=${l.name}>
              ${
                l.url
                  ? html`<a
                      slot="description"
                      href=${l.url}
                      target="_blank"
                      rel="noopener"
                      >Details</a
                    >`
                  : nothing
              }
            </moz-radio>`,
        )}
        ${
          this.theme
            ? nothing
            : html`<moz-radio value=${CUSTOM_LICENSE} label="Other"></moz-radio>`
        }
      </moz-radio-group>
      ${
        this.license === CUSTOM_LICENSE
          ? html`<moz-input-text
                label="License name"
                full-width
                error=${this.errors.license_name ?? ''}
                .value=${this.licenseName}
                @input=${(e: Event) => this.#emit('license_name', e)}
              ></moz-input-text>
              <moz-textarea
                label="License text"
                full-width
                error=${this.errors.license_text ?? ''}
                .value=${this.licenseText}
                @input=${(e: Event) => this.#emit('license_text', e)}
              ></moz-textarea>`
          : nothing
      }`;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'license-field': LicenseField;
  }
  interface HTMLElementEventMap {
    'license-change': CustomEvent<LicenseFieldChange>;
  }
}
