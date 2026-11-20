import { css, html, LitElement, nothing } from 'lit';
import { customElement, property } from 'lit/decorators.js';
import {
  localized,
  type VersionLicense,
  type VersionLicenseEdit,
} from '../../data';
import { ApiError } from '../../data/http';
import type { FormController } from '../../foundations/form';
import { EXTENSION_LICENSES, THEME_LICENSES } from '../../licenses';
import { emit } from '../../utils/helper';

export const CUSTOM_LICENSE = 'other';

export type LicenseFieldKey = 'license' | 'license_name' | 'license_text';

export type LicenseFieldChange = { field: LicenseFieldKey; value: string };

export type LicenseDraft = {
  license?: string;
  license_name?: string;
  license_text?: string;
};

export function licenseDraft(license?: VersionLicense | null): LicenseDraft {
  if (!license) return {};
  if (license.is_custom) {
    return {
      license: CUSTOM_LICENSE,
      license_name: localized(license.name),
      license_text: localized(license.text),
    };
  }
  return { license: license.slug ?? undefined };
}

export function licenseChanged(d: LicenseDraft, saved: LicenseDraft = {}) {
  if (d.license === undefined) return false;
  return (
    d.license !== saved.license ||
    (d.license === CUSTOM_LICENSE &&
      ((d.license_name ?? '') !== (saved.license_name ?? '') ||
        (d.license_text ?? '') !== (saved.license_text ?? '')))
  );
}

export function licenseEdit(d: LicenseDraft): VersionLicenseEdit | undefined {
  if (d.license === CUSTOM_LICENSE) {
    return {
      custom_license: {
        name: (d.license_name ?? '').trim(),
        text: (d.license_text ?? '').trim(),
      },
    };
  }
  return d.license ? { license: d.license } : undefined;
}

export function customLicenseErrors(d: LicenseDraft) {
  const errors: Record<string, string> = {};
  if (d.license !== CUSTOM_LICENSE) return errors;
  if (!d.license_name?.trim()) errors.license_name = 'Enter the license name.';
  if (!d.license_text?.trim()) errors.license_text = 'Enter the license text.';
  return errors;
}

const LICENSE_URLS = new Map(
  [...EXTENSION_LICENSES, ...THEME_LICENSES].map((l) => [l.slug, l.url]),
);

export const licenseUrl = (slug?: string | null) =>
  slug ? LICENSE_URLS.get(slug) : undefined;

const LICENSE_ERROR_FIELDS: Record<string, keyof LicenseDraft> = {
  license: 'license',
  custom_license: 'license',
  'custom_license.name': 'license_name',
  'custom_license.text': 'license_text',
};

export function routeVersionErrors(e: unknown, nested = false): unknown {
  if (!(e instanceof ApiError)) return e;
  const fields: Record<string, string> = {};
  const general = e.detail ? [e.detail] : [];
  for (const [key, text] of Object.entries(e.fields)) {
    if (nested && key !== 'version' && !key.startsWith('version.')) {
      fields[key] = text;
      continue;
    }
    const field =
      LICENSE_ERROR_FIELDS[nested ? key.slice('version.'.length) : key];
    if (field)
      fields[field] = fields[field] ? `${fields[field]} ${text}` : text;
    else general.push(text);
  }
  return new ApiError(e.status, e.message, fields, general.join(' • '));
}

export function licenseField<D extends LicenseDraft>(
  form: FormController<D>,
  theme = false,
) {
  return html`<license-field
    ?theme=${theme}
    license=${form.value('license') ?? ''}
    license-name=${form.value('license_name') ?? ''}
    license-text=${form.value('license_text') ?? ''}
    .errors=${{
      license: form.fieldError('license'),
      license_name: form.fieldError('license_name'),
      license_text: form.fieldError('license_text'),
    }}
    @license-change=${(e: CustomEvent<LicenseFieldChange>) =>
      form.set(e.detail.field, e.detail.value as D[LicenseFieldKey])}
  ></license-field>`;
}

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
