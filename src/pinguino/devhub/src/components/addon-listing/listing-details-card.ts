import { html, nothing, type PropertyValues } from 'lit';
import { customElement, property } from 'lit/decorators.js';
import { unsafeHTML } from 'lit/directives/unsafe-html.js';
import { SITE_URL } from '../../base';
import {
  type Addon,
  type AddonListingEdit,
  addonFromUpload,
  addonSourceQuery,
  categoriesQuery,
  createVersion,
  type EulaPolicyEdit,
  eulaPolicyQuery,
  updateAddon,
  updateEulaPolicy,
  updateVersionLicense,
  type VersionLicense,
  type VersionLicenseEdit,
  versionQuery,
} from '../../data';
import { localized } from '../../data/api';
import { ApiError } from '../../data/http';
import {
  FieldError,
  FormController,
  textArea,
  textField,
} from '../../foundations/form';
import { emit, navigateTo, slugify } from '../../utils/helper';
import { MARKDOWN_TAGS, sanitizeHTML } from '../../utils/sanitizeHTML';
import { CUSTOM_LICENSE, type LicenseFieldChange } from './license';
import { SectionCard } from './section-card';

const MAX_CATEGORIES = 3;

type LicenseDraft = {
  license?: string;
  license_name?: string;
  license_text?: string;
};

// The edit draft: the add-on PATCH fields (API-named, so field errors land on
// the right input) plus the EULA/privacy text and license, which save via their own endpoints.
type ListingDraft = AddonListingEdit &
  LicenseDraft & {
    has_eula?: boolean;
    eula?: string;
    has_privacy_policy?: boolean;
    privacy_policy?: string;
  };

function licenseDraft(license?: VersionLicense | null): LicenseDraft {
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

const LICENSE_ERROR_FIELDS: Record<string, keyof LicenseDraft> = {
  license: 'license',
  custom_license: 'license',
  'custom_license.name': 'license_name',
  'custom_license.text': 'license_text',
};

function routeVersionErrors(e: unknown, nested = false): unknown {
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

// The listing flags, shown as (read-only) checkboxes with help text so the view
// mirrors the edit form. `key` indexes Addon['flags'].
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

const FLAG = Object.fromEntries(FLAGS.map((f) => [f.key, f])) as Record<
  (typeof FLAGS)[number]['key'],
  (typeof FLAGS)[number]
>;

@customElement('listing-details-card')
export class ListingDetailsCard extends SectionCard {
  @property({ type: Number }) versionId?: number;
  @property() upload?: string;
  @property({ type: Boolean, attribute: 'new-version' }) showListing = false;

  #form = new FormController<ListingDraft>(this);
  #categories = categoriesQuery(this);
  #version = versionQuery(
    this,
    () => this.addon?.slug ?? '',
    () => this.versionId ?? 0,
  );
  // Policy text for the view-mode preview; only fetched when the add-on has one.
  #eula = eulaPolicyQuery(
    this,
    () => this.addon?.slug ?? '',
    () => this.#hasPolicy(),
  );
  #eulaSource = eulaPolicyQuery(
    this,
    () => this.addon?.slug ?? '',
    () => this.#hasPolicy(),
    true,
  );
  #source = addonSourceQuery(
    this,
    () => this.addon?.slug ?? '',
    () => Boolean(this.addon?.description),
  );
  #licenseBaseline?: LicenseDraft;
  #startedDraftKey?: string;
  #slugSynced = true;

  #hasPolicy() {
    return Boolean(
      this.addon?.flags?.hasEula || this.addon?.flags?.hasPrivacyPolicy,
    );
  }

  get #eulaBaseline() {
    return this.#eulaSource().data ?? { eula: '', privacyPolicy: '' };
  }

  get #editing() {
    return this.editOnly || this.#form.editing;
  }

  get #creating() {
    return Boolean(this.upload);
  }

  get #hasLicense() {
    return this.#creating || Boolean(this.versionId);
  }

  get #isTheme() {
    return this.addon.kind === 'theme';
  }

  get #draftKey() {
    return this.#creating ? this.upload : this.addon.slug;
  }

  get #licenseName() {
    return localized(this.#version().data?.license?.name) || this.addon.license;
  }

  willUpdate(changed: PropertyValues) {
    if (changed.has('versionId')) this.#licenseBaseline = undefined;
    if (this.editOnly && this.#draftKey !== this.#startedDraftKey) {
      this.#startEdit();
    }
    if (!this.#editing) return;
    const source = this.#source().data;
    if (source && this.#form.value('description') === undefined) {
      this.#form.set('description', source.description ?? '');
    }
    const policy = this.#eulaSource().data;
    if (policy && this.#form.value('eula') === undefined) {
      this.#form.set('eula', policy.eula);
    }
    if (policy && this.#form.value('privacy_policy') === undefined) {
      this.#form.set('privacy_policy', policy.privacyPolicy);
    }
    const version = this.#version().data;
    if (!this.#licenseBaseline && version) {
      this.#licenseBaseline = licenseDraft(version.license);
      if (this.#form.value('license') === undefined) {
        for (const [key, value] of Object.entries(this.#licenseBaseline)) {
          this.#form.set(key as keyof LicenseDraft, value);
        }
      }
    }
  }

  #startEdit() {
    const a = this.addon;
    this.#startedDraftKey = this.#draftKey;
    this.#licenseBaseline = this.#creating ? {} : undefined;
    this.#slugSynced = !a.slug;
    this.#form.start({
      name: a.name,
      slug: a.slug || slugify(a.name),
      summary: a.summary ?? '',
      homepage: a.homepageUrl ?? '',
      support_email: a.supportEmail ?? '',
      support_url: a.supportUrl ?? '',
      categories: [...(a.categories ?? [])],
      is_experimental: a.flags?.experimental ?? false,
      requires_payment: a.flags?.requiresPayment ?? false,
      has_eula: a.flags?.hasEula ?? false,
      has_privacy_policy: a.flags?.hasPrivacyPolicy ?? false,
    });
  }

  #toggleCategory(slug: string, checked: boolean) {
    const current = this.#form.value('categories') ?? [];
    if (checked) {
      if (current.includes(slug) || current.length >= MAX_CATEGORIES) return;
      this.#form.set('categories', [...current, slug]);
    } else {
      this.#form.set(
        'categories',
        current.filter((s) => s !== slug),
      );
    }
  }

  // The add-on PATCH fields the user actually changed, for a minimal body;
  // each key is spread in only when its value differs from the saved add-on.
  #changedListing(d: ListingDraft): AddonListingEdit {
    const a = this.addon;
    const cats = d.categories ?? [];
    const original = a.categories ?? [];
    const categoriesChanged =
      cats.length !== original.length ||
      cats.some((c) => !original.includes(c));
    return {
      ...(d.name !== a.name && { name: d.name }),
      ...(!this.#slugSynced && d.slug !== a.slug && { slug: d.slug }),
      ...((d.summary ?? '') !== (a.summary ?? '') && { summary: d.summary }),
      ...((d.description ?? '') !==
        (this.#source().data?.description ?? '') && {
        description: d.description,
      }),
      ...((d.homepage ?? '') !== (a.homepageUrl ?? '') && {
        homepage: d.homepage,
      }),
      ...((d.support_email ?? '') !== (a.supportEmail ?? '') && {
        support_email: d.support_email,
      }),
      ...((d.support_url ?? '') !== (a.supportUrl ?? '') && {
        support_url: d.support_url,
      }),
      ...(categoriesChanged && { categories: cats }),
      ...((d.is_experimental ?? false) !== (a.flags?.experimental ?? false) && {
        is_experimental: d.is_experimental,
      }),
      ...((d.requires_payment ?? false) !==
        (a.flags?.requiresPayment ?? false) && {
        requires_payment: d.requires_payment,
      }),
    };
  }

  // The policy changes to persist, diffed against the fetched baseline, or null
  // when nothing changed. A policy switched off (or emptied) becomes a null,
  // which clears it.
  #changedEula(d: ListingDraft) {
    const nextEula = d.has_eula ? (d.eula ?? '').trim() : '';
    const nextPrivacy = d.has_privacy_policy
      ? (d.privacy_policy ?? '').trim()
      : '';
    const out: EulaPolicyEdit = {};
    if (nextEula && nextEula !== this.#eulaBaseline.eula) out.eula = nextEula;
    else if (!nextEula && this.#eulaBaseline.eula) out.eula = null;
    if (nextPrivacy && nextPrivacy !== this.#eulaBaseline.privacyPolicy)
      out.privacyPolicy = nextPrivacy;
    else if (!nextPrivacy && this.#eulaBaseline.privacyPolicy)
      out.privacyPolicy = null;
    return Object.keys(out).length ? out : null;
  }

  #licenseEdit(d: LicenseDraft): VersionLicenseEdit | undefined {
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

  #licenseChanged(d: LicenseDraft) {
    if (d.license === undefined) return false;
    const saved = this.#licenseBaseline ?? {};
    return (
      d.license !== saved.license ||
      (d.license === CUSTOM_LICENSE &&
        ((d.license_name ?? '') !== (saved.license_name ?? '') ||
          (d.license_text ?? '') !== (saved.license_text ?? '')))
    );
  }

  #checkRequired(d: ListingDraft) {
    const errors: Record<string, string> = {};
    if (this.#creating) {
      if (!d.name?.trim()) errors.name = 'Enter a name for your add-on.';
      if (!d.summary?.trim()) {
        errors.summary = 'Enter a summary of your add-on.';
      }
      if (!d.categories?.length) {
        errors.categories = 'Choose at least one category.';
      }
      if (!d.license) errors.license = 'Choose a license for your add-on.';
    }
    if (d.license === CUSTOM_LICENSE) {
      if (!d.license_name?.trim()) {
        errors.license_name = 'Enter the license name.';
      }
      if (!d.license_text?.trim()) {
        errors.license_text = 'Enter the license text.';
      }
    }
    if (Object.keys(errors).length) throw new FieldError(errors);
  }

  #licenseOf(d: LicenseDraft): LicenseDraft {
    const { license, license_name, license_text } = d;
    return { license, license_name, license_text };
  }

  async save() {
    let saved = false;
    await this.#form.submit(async (d) => {
      await (this.#creating ? this.#create(d) : this.#update(d));
      saved = true;
    });
    return saved;
  }

  async #create(d: ListingDraft) {
    this.#checkRequired(d);
    if (this.showListing) return this.#createVersion(d);
    const { addon, version } = await addonFromUpload({
      ...this.#changedListing(d),
      version: { upload: this.upload ?? '', ...this.#licenseEdit(d) },
    }).catch((e: unknown) => {
      throw routeVersionErrors(e, true);
    });
    this.#startedDraftKey = addon.slug;
    this.#licenseBaseline = this.#licenseOf(d);
    emit(this, 'addon-create', { addon, version });
    const eula = this.#changedEula(d);
    if (eula) {
      await updateEulaPolicy(addon.slug, eula);
    }
  }

  async #createVersion(d: ListingDraft) {
    const previousSlug = this.addon.slug;
    const listing = this.#changedListing(d);
    if (Object.keys(listing).length) {
      await updateAddon(previousSlug, listing);
    }
    const slug = listing.slug || previousSlug;
    if (slug !== previousSlug) emit(this, 'addon-slug-change', { slug });
    const version = await createVersion(
      slug,
      this.upload ?? '',
      this.#licenseEdit(d),
    ).catch((e: unknown) => {
      throw routeVersionErrors(e);
    });
    this.#startedDraftKey = slug;
    this.#licenseBaseline = this.#licenseOf(d);
    emit(this, 'version-create', { slug, version });
    const eula = this.#changedEula(d);
    if (eula) {
      await updateEulaPolicy(slug, eula);
    }
  }

  async #update(d: ListingDraft) {
    const previousSlug = this.addon.slug;
    const listing = this.#changedListing(d);
    const eula = this.#changedEula(d);
    const license = this.#licenseChanged(d) && this.#licenseEdit(d);
    const { versionId } = this;
    if (license) this.#checkRequired(d);
    if (Object.keys(listing).length) {
      await updateAddon(previousSlug, listing);
    }
    const slug = listing.slug || previousSlug;
    if (license && versionId) {
      await updateVersionLicense(
        slug,
        versionId,
        license.license,
        license.custom_license,
      ).catch((e: unknown) => {
        throw routeVersionErrors(e);
      });
      this.#licenseBaseline = this.#licenseOf(d);
    }
    if (eula) {
      await updateEulaPolicy(slug, eula);
    }
    // The slug lives in the page URL. On the edit page, point the router at
    // the new slug; in a submission flow, the flow moves to its next step under
    // it instead.
    if (slug !== previousSlug) {
      this.#startedDraftKey = slug;
      emit(this, 'addon-slug-change', { slug });
      if (!this.embedded) {
        navigateTo(
          location.pathname.replace(`/addon/${previousSlug}`, `/addon/${slug}`),
        );
      }
    }
  }

  // Readable name for a category slug, via the fetched list (falls back to the
  // slug prettified while the list loads).
  #categoryName(slug: string): string {
    const match = this.#categories().data?.find((c) => c.slug === slug);
    if (match) return match.name;
    return slug.replace(/-/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
  }

  // Categories offered in the edit grid: those matching the add-on's type.
  #categoryChoices() {
    const apiType = this.addon.kind === 'theme' ? 'statictheme' : 'extension';
    return (this.#categories().data ?? []).filter((c) => c.type === apiType);
  }

  // "Add-on URL" edit: the listing-URL base shown as static text with the slug
  // input inline beside it.
  #urlField() {
    const form = this.#form;
    // Path varies.
    const base = `${SITE_URL}/…/`;
    return html`<div class="url-field">
      <span class="url-label">Add-on URL</span>
      <div class="url-row">
        <span class="url-base">${base}</span>
        <moz-input-text
          class="url-slug"
          aria-label="Add-on URL slug"
          full-width
          error=${form.fieldError('slug')}
          .value=${form.value('slug') ?? ''}
          @input=${(e: Event) => {
            this.#slugSynced = false;
            form.set('slug', (e.target as HTMLInputElement).value);
          }}
        ></moz-input-text>
      </div>
    </div>`;
  }

  #nameField() {
    const form = this.#form;
    return html`<moz-input-text
      label="Add-on name"
      full-width
      error=${form.fieldError('name')}
      .value=${form.value('name') ?? ''}
      @input=${(e: Event) => {
        const name = (e.target as HTMLInputElement).value;
        form.set('name', name);
        if (this.#slugSynced) form.set('slug', slugify(name));
      }}
    ></moz-input-text>`;
  }

  #editForm() {
    const form = this.#form;
    return html`
      <div class="form">
        ${this.errorBar(form.error)}
        ${this.#nameField()}
        ${this.#urlField()}
        ${textField(form, 'homepage', 'Homepage of the add-on', 'url')}
        ${textField(form, 'support_url', 'Support Website', 'url')}
        ${textField(form, 'support_email', 'Support Email', 'email')}
        ${textArea(form, 'summary', 'Summary')}
        ${textArea(form, 'description', 'Description')}
        ${this.#categoriesField()}
        ${this.#isTheme ? nothing : this.#flagFields()}
        ${this.#licenseField()}
      </div>
    `;
  }

  #flagFields() {
    const form = this.#form;
    return html`
      <hr class="divider" />
      <moz-checkbox
        label=${FLAG.experimental.label}
        description=${FLAG.experimental.description}
        ?checked=${form.value('is_experimental')}
        @change=${(e: Event) =>
          form.set('is_experimental', (e.target as HTMLInputElement).checked)}
      ></moz-checkbox>
      <moz-checkbox
        label=${FLAG.requiresPayment.label}
        description=${FLAG.requiresPayment.description}
        ?checked=${form.value('requires_payment')}
        @change=${(e: Event) =>
          form.set('requires_payment', (e.target as HTMLInputElement).checked)}
      ></moz-checkbox>
      ${this.#policyField({
        flag: FLAG.hasEula,
        hasKey: 'has_eula',
        textKey: 'eula',
      })}
      ${this.#policyField({
        flag: FLAG.hasPrivacyPolicy,
        hasKey: 'has_privacy_policy',
        textKey: 'privacy_policy',
      })}
    `;
  }

  #licenseField() {
    if (!this.#hasLicense) return nothing;
    const form = this.#form;
    return html`<hr class="divider" />
      <license-field
        ?theme=${this.#isTheme}
        license=${form.value('license') ?? ''}
        license-name=${form.value('license_name') ?? ''}
        license-text=${form.value('license_text') ?? ''}
        .errors=${{
          license: form.fieldError('license'),
          license_name: form.fieldError('license_name'),
          license_text: form.fieldError('license_text'),
        }}
        @license-change=${(e: CustomEvent<LicenseFieldChange>) =>
          form.set(e.detail.field, e.detail.value)}
      ></license-field>`;
  }

  #categoriesField() {
    const choices = this.#categoryChoices();
    const selected = this.#form.value('categories') ?? [];
    const atMax = selected.length >= MAX_CATEGORIES;
    const error = this.#form.fieldError('categories');
    return html`<div class="cat-field">
      <p class="cat-label">Categories</p>
      <p class="cat-help">
        Select up to ${MAX_CATEGORIES} categories for this add-on.
      </p>
      <div class="cat-grid">
        ${choices.map((c) => {
          const checked = selected.includes(c.slug);
          return html`<moz-checkbox
            label=${c.name}
            ?checked=${checked}
            ?disabled=${!checked && atMax}
            @change=${(e: Event) =>
              this.#toggleCategory(
                c.slug,
                (e.target as HTMLInputElement).checked,
              )}
          ></moz-checkbox>`;
        })}
      </div>
      ${
        error ? html`<p class="group-error" role="alert">${error}</p>` : nothing
      }
    </div>`;
  }

  // A policy toggle (EULA / privacy) that reveals a textarea when checked.
  #policyField(opts: {
    flag: { label: string; description: string };
    hasKey: 'has_eula' | 'has_privacy_policy';
    textKey: 'eula' | 'privacy_policy';
  }) {
    const form = this.#form;
    const checked = Boolean(form.value(opts.hasKey));
    return html`<div class="policy">
      <moz-checkbox
        label=${opts.flag.label}
        description=${opts.flag.description}
        ?checked=${checked}
        @change=${(e: Event) =>
          form.set(opts.hasKey, (e.target as HTMLInputElement).checked)}
      ></moz-checkbox>
      ${checked ? textArea(form, opts.textKey) : nothing}
    </div>`;
  }

  // Read-only preview of a policy's text in a collapsible moz-details, shown
  // under its own checkbox only when the add-on has that policy (and text).
  #policyDetail(key: 'hasEula' | 'hasPrivacyPolicy', heading: string) {
    if (!this.addon.flags?.[key]) return nothing;
    const data = this.#eula().data;
    const text = key === 'hasEula' ? data?.eula : data?.privacyPolicy;
    if (!text) return nothing;
    return html`<moz-details heading=${heading} class="policy-preview">
      ${unsafeHTML(sanitizeHTML(text, MARKDOWN_TAGS))}
    </moz-details>`;
  }

  #view(a: Addon) {
    const flags = a.flags ?? {};
    return html`
      <dl>
        ${this.row('Add-on name', a.name)}
        ${this.row('Add-on URL', `${SITE_URL}/…/${a.slug}`)}
        ${this.row('Homepage of the add-on', this.link(a.homepageUrl))}
        ${this.row('Support Website', this.link(a.supportUrl))}
        ${this.row('Support Email', a.supportEmail)}
        ${this.row('Summary', a.summary)}
        ${this.row('Description', unsafeHTML(sanitizeHTML(a.description, MARKDOWN_TAGS)))}
        ${this.row(
          'Categories',
          a.categories?.length
            ? html`<div class="categories">
                ${a.categories.map(
                  (c) =>
                    html`<moz-status-badge
                      >${this.#categoryName(c)}</moz-status-badge
                    >`,
                )}
              </div>`
            : null,
        )}
        ${this.#hasLicense ? this.row('License', this.#licenseName) : nothing}
      </dl>
      ${this.#isTheme ? nothing : this.#flagsView(flags)}
    `;
  }

  #flagsView(flags: NonNullable<Addon['flags']>) {
    return html`
      <div class="flags">
        ${FLAGS.map(
          (f) => html`<moz-checkbox
              disabled
              ?checked=${Boolean(flags[f.key])}
              label=${f.label}
              description=${f.description}
            ></moz-checkbox>
            ${
              f.key === 'hasEula'
                ? this.#policyDetail('hasEula', 'End-User License Agreement')
                : f.key === 'hasPrivacyPolicy'
                  ? this.#policyDetail('hasPrivacyPolicy', 'Privacy Policy')
                  : nothing
            }`,
        )}
      </div>
    `;
  }

  render() {
    return this.frame(
      'details',
      html`${this.cardHead(
        'details',
        this.draftActions(
          this.#form,
          () => this.#startEdit(),
          () => this.save(),
        ),
      )}
      ${this.#editing ? this.#editForm() : this.#view(this.addon)}`,
    );
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'listing-details-card': ListingDetailsCard;
  }
}
