import type { InputType } from '@mozilla/acorn-web-components';
import { html, nothing } from 'lit';
import { customElement, state } from 'lit/decorators.js';
import {
  type Addon,
  type AddonListingEdit,
  categoriesQuery,
  fetchEulaPolicy,
  updateAddon,
  updateEulaPolicy,
} from '../../data';
import { SectionCard } from './section-card';

const MAX_CATEGORIES = 3;

// The edit draft: the main listing fields plus the EULA/privacy text, which are
// saved through a separate endpoint.
type ListingDraft = AddonListingEdit & {
  hasEula?: boolean;
  eula?: string;
  hasPrivacyPolicy?: boolean;
  privacyPolicy?: string;
};

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

@customElement('listing-details-card')
export class ListingDetailsCard extends SectionCard {
  @state() private draft: ListingDraft = {};

  #categories = categoriesQuery(this);
  // Original EULA/privacy text, fetched on edit open, to diff against on save.
  #eulaBaseline = { eula: '', privacyPolicy: '' };

  #startEdit() {
    const a = this.addon;
    this.draft = {
      name: a.name,
      summary: a.summary ?? '',
      description: a.description ?? '',
      homepageUrl: a.homepageUrl ?? '',
      supportEmail: a.supportEmail ?? '',
      supportUrl: a.supportUrl ?? '',
      categories: [...(a.categories ?? [])],
      experimental: a.flags?.experimental ?? false,
      requiresPayment: a.flags?.requiresPayment ?? false,
      hasEula: a.flags?.hasEula ?? false,
      hasPrivacyPolicy: a.flags?.hasPrivacyPolicy ?? false,
    };
    this.error = '';
    this.editing = true;
    // The list API doesn't carry the EULA/privacy text; fetch it so the
    // textareas start from the saved values.
    fetchEulaPolicy(a.slug)
      .then((p) => {
        this.#eulaBaseline = p;
        this.draft = {
          ...this.draft,
          eula: this.draft.eula ?? p.eula,
          privacyPolicy: this.draft.privacyPolicy ?? p.privacyPolicy,
        };
      })
      .catch(() => {
        /* leave textareas empty if the fetch fails */
      });
  }

  #set<K extends keyof ListingDraft>(key: K, value: ListingDraft[K]) {
    this.draft = { ...this.draft, [key]: value };
  }

  #toggleCategory(slug: string, checked: boolean) {
    const current = this.draft.categories ?? [];
    if (checked) {
      if (current.includes(slug) || current.length >= MAX_CATEGORIES) return;
      this.#set('categories', [...current, slug]);
    } else {
      this.#set(
        'categories',
        current.filter((s) => s !== slug),
      );
    }
  }

  // Main-listing fields the user actually changed, for a minimal PATCH body.
  #changedListing(): AddonListingEdit {
    const a = this.addon;
    const d = this.draft;
    const out: AddonListingEdit = {};
    if (d.name !== a.name) out.name = d.name;
    if ((d.summary ?? '') !== (a.summary ?? '')) out.summary = d.summary;
    if ((d.description ?? '') !== (a.description ?? ''))
      out.description = d.description;
    if ((d.homepageUrl ?? '') !== (a.homepageUrl ?? ''))
      out.homepageUrl = d.homepageUrl;
    if ((d.supportEmail ?? '') !== (a.supportEmail ?? ''))
      out.supportEmail = d.supportEmail;
    if ((d.supportUrl ?? '') !== (a.supportUrl ?? ''))
      out.supportUrl = d.supportUrl;
    const cats = d.categories ?? [];
    const original = a.categories ?? [];
    if (
      cats.length !== original.length ||
      cats.some((c) => !original.includes(c))
    )
      out.categories = cats;
    if ((d.experimental ?? false) !== (a.flags?.experimental ?? false))
      out.experimental = d.experimental;
    if ((d.requiresPayment ?? false) !== (a.flags?.requiresPayment ?? false))
      out.requiresPayment = d.requiresPayment;
    return out;
  }

  // Returns the changed, non-empty policy text, or null when nothing changed.
  // The endpoint rejects blank values, so clearing a policy (unchecking it)
  // isn't supported here yet — only setting/updating non-empty text.
  #changedEula() {
    const d = this.draft;
    const nextEula = d.hasEula ? (d.eula ?? '').trim() : '';
    const nextPrivacy = d.hasPrivacyPolicy
      ? (d.privacyPolicy ?? '').trim()
      : '';
    const out: { eula?: string; privacyPolicy?: string } = {};
    if (nextEula && nextEula !== this.#eulaBaseline.eula) out.eula = nextEula;
    if (nextPrivacy && nextPrivacy !== this.#eulaBaseline.privacyPolicy)
      out.privacyPolicy = nextPrivacy;
    return Object.keys(out).length ? out : null;
  }

  async #save() {
    this.saving = true;
    this.error = '';
    try {
      const listing = this.#changedListing();
      const eula = this.#changedEula();
      if (Object.keys(listing).length) {
        await updateAddon(this.addon.slug, listing);
      }
      if (eula) {
        await updateEulaPolicy(this.addon.slug, eula);
      }
      this.editing = false;
    } catch (e) {
      this.error = e instanceof Error ? e.message : 'Could not save changes.';
    } finally {
      this.saving = false;
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

  #textField(
    label: string,
    key: 'name' | 'homepageUrl' | 'supportEmail' | 'supportUrl',
    type: InputType = 'text',
  ) {
    return html`<moz-input-text
      label=${label}
      type=${type}
      full-width
      .value=${this.draft[key] ?? ''}
      @input=${(e: Event) =>
        this.#set(key, (e.target as HTMLInputElement).value)}
    ></moz-input-text>`;
  }

  #textArea(label: string, key: 'summary' | 'description') {
    return html`<moz-textarea
      label=${label}
      .value=${this.draft[key] ?? ''}
      full-width
      @input=${(e: Event) =>
        this.#set(key, (e.target as HTMLTextAreaElement).value)}
    ></moz-textarea>`;
  }

  #form() {
    const d = this.draft;
    return html`
      <div class="form">
        ${this.errorBar()}
        ${this.#textField('Add-on name', 'name')}
        ${this.#textField('Homepage of the add-on', 'homepageUrl', 'url')}
        ${this.#textField('Support email', 'supportEmail', 'email')}
        ${this.#textField('Support site', 'supportUrl', 'url')}
        ${this.#textArea('Summary', 'summary')}
        ${this.#textArea('Description', 'description')}
        ${this.#categoriesField()}
        <hr class="divider" />
        <moz-checkbox
          label="Experimental"
          ?checked=${d.experimental}
          @change=${(e: Event) =>
            this.#set('experimental', (e.target as HTMLInputElement).checked)}
        ></moz-checkbox>
        <moz-checkbox
          label="This add-on requires payment, non-free services or software, or additional hardware"
          ?checked=${d.requiresPayment}
          @change=${(e: Event) =>
            this.#set(
              'requiresPayment',
              (e.target as HTMLInputElement).checked,
            )}
        ></moz-checkbox>
        ${this.#policyField({
          label: 'This add-on has an End-User License Agreement',
          hasKey: 'hasEula',
          textKey: 'eula',
        })}
        ${this.#policyField({
          label: 'This add-on has a Privacy Policy',
          hasKey: 'hasPrivacyPolicy',
          textKey: 'privacyPolicy',
        })}
      </div>
    `;
  }

  #categoriesField() {
    const choices = this.#categoryChoices();
    const selected = this.draft.categories ?? [];
    const atMax = selected.length >= MAX_CATEGORIES;
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
    </div>`;
  }

  // A policy toggle (EULA / privacy) that reveals a textarea when checked.
  #policyField(opts: {
    label: string;
    hasKey: 'hasEula' | 'hasPrivacyPolicy';
    textKey: 'eula' | 'privacyPolicy';
  }) {
    const d = this.draft;
    const checked = Boolean(d[opts.hasKey]);
    return html`<div class="policy">
      <moz-checkbox
        label=${opts.label}
        ?checked=${checked}
        @change=${(e: Event) =>
          this.#set(opts.hasKey, (e.target as HTMLInputElement).checked)}
      ></moz-checkbox>
      ${
        checked
          ? html`<moz-textarea
            label=${opts.label}
            full-width
            .value=${d[opts.textKey] ?? ''}
            @input=${(e: Event) =>
              this.#set(opts.textKey, (e.target as HTMLTextAreaElement).value)}
          ></moz-textarea>`
          : nothing
      }
    </div>`;
  }

  #view(a: Addon) {
    const flags = a.flags ?? {};
    return html`
      <dl>
        ${this.row('Add-on name', a.name)}
        ${this.row('Add-on URL', this.link(a.listingUrl))}
        ${this.row('Homepage of the add-on', this.link(a.homepageUrl))}
        ${this.row('Support Website', this.link(a.supportUrl))}
        ${this.row('Support Email', a.supportEmail)}
        ${this.row('Summary', a.summary)}
        ${this.row('Description', a.description)}
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
    `;
  }

  render() {
    return html`<moz-card
      appearance="outline"
      spacing="spacious"
      id="listing-details"
    >
      ${this.cardHead(
        'listing-details',
        this.draftActions(
          () => this.#startEdit(),
          () => this.#save(),
        ),
      )}
      ${this.editing ? this.#form() : this.#view(this.addon)}
    </moz-card>`;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'listing-details-card': ListingDetailsCard;
  }
}
