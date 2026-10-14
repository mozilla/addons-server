import { html, nothing } from 'lit';
import { customElement } from 'lit/decorators.js';
import {
  type Addon,
  type AddonListingEdit,
  categoriesQuery,
  fetchEulaPolicy,
  updateAddon,
  updateEulaPolicy,
} from '../../data';
import { FormController, textArea, textField } from '../../foundations/form';
import { SectionCard } from './section-card';

const MAX_CATEGORIES = 3;

// The edit draft: the add-on PATCH fields (API-named, so field errors land on
// the right input) plus the EULA/privacy text, which saves via its own endpoint.
type ListingDraft = AddonListingEdit & {
  has_eula?: boolean;
  eula?: string;
  has_privacy_policy?: boolean;
  privacy_policy?: string;
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
  #form = new FormController<ListingDraft>(this);
  #categories = categoriesQuery(this);
  // Original EULA/privacy text, fetched on edit open, to diff against on save.
  #eulaBaseline = { eula: '', privacyPolicy: '' };

  #startEdit() {
    const a = this.addon;
    this.#form.start({
      name: a.name,
      summary: a.summary ?? '',
      description: a.description ?? '',
      homepage: a.homepageUrl ?? '',
      support_email: a.supportEmail ?? '',
      support_url: a.supportUrl ?? '',
      categories: [...(a.categories ?? [])],
      is_experimental: a.flags?.experimental ?? false,
      requires_payment: a.flags?.requiresPayment ?? false,
      has_eula: a.flags?.hasEula ?? false,
      has_privacy_policy: a.flags?.hasPrivacyPolicy ?? false,
    });
    // The list API doesn't carry the EULA/privacy text; fetch it so the
    // textareas start from the saved values.
    fetchEulaPolicy(a.slug)
      .then((p) => {
        this.#eulaBaseline = p;
        this.#form.set('eula', this.#form.value('eula') ?? p.eula);
        this.#form.set(
          'privacy_policy',
          this.#form.value('privacy_policy') ?? p.privacyPolicy,
        );
      })
      .catch(() => {
        /* leave textareas empty if the fetch fails */
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

  // The add-on PATCH fields the user actually changed, for a minimal body.
  #changedListing(d: ListingDraft): AddonListingEdit {
    const a = this.addon;
    const out: AddonListingEdit = {};
    if (d.name !== a.name) out.name = d.name;
    if ((d.summary ?? '') !== (a.summary ?? '')) out.summary = d.summary;
    if ((d.description ?? '') !== (a.description ?? ''))
      out.description = d.description;
    if ((d.homepage ?? '') !== (a.homepageUrl ?? '')) out.homepage = d.homepage;
    if ((d.support_email ?? '') !== (a.supportEmail ?? ''))
      out.support_email = d.support_email;
    if ((d.support_url ?? '') !== (a.supportUrl ?? ''))
      out.support_url = d.support_url;
    const cats = d.categories ?? [];
    const original = a.categories ?? [];
    if (
      cats.length !== original.length ||
      cats.some((c) => !original.includes(c))
    )
      out.categories = cats;
    if ((d.is_experimental ?? false) !== (a.flags?.experimental ?? false))
      out.is_experimental = d.is_experimental;
    if ((d.requires_payment ?? false) !== (a.flags?.requiresPayment ?? false))
      out.requires_payment = d.requires_payment;
    return out;
  }

  // Returns the changed, non-empty policy text, or null when nothing changed.
  // The endpoint rejects blank values, so clearing a policy (unchecking it)
  // isn't supported here yet — only setting/updating non-empty text.
  #changedEula(d: ListingDraft) {
    const nextEula = d.has_eula ? (d.eula ?? '').trim() : '';
    const nextPrivacy = d.has_privacy_policy
      ? (d.privacy_policy ?? '').trim()
      : '';
    const out: { eula?: string; privacyPolicy?: string } = {};
    if (nextEula && nextEula !== this.#eulaBaseline.eula) out.eula = nextEula;
    if (nextPrivacy && nextPrivacy !== this.#eulaBaseline.privacyPolicy)
      out.privacyPolicy = nextPrivacy;
    return Object.keys(out).length ? out : null;
  }

  #save() {
    return this.#form.submit(async (d) => {
      const listing = this.#changedListing(d);
      const eula = this.#changedEula(d);
      if (Object.keys(listing).length) {
        await updateAddon(this.addon.slug, listing);
      }
      if (eula) {
        await updateEulaPolicy(this.addon.slug, eula);
      }
    });
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

  #editForm() {
    const form = this.#form;
    return html`
      <div class="form">
        ${this.errorBar(form.error)}
        ${textField(form, 'name', 'Add-on name')}
        ${textField(form, 'homepage', 'Homepage of the add-on', 'url')}
        ${textField(form, 'support_email', 'Support email', 'email')}
        ${textField(form, 'support_url', 'Support site', 'url')}
        ${textArea(form, 'summary', 'Summary')}
        ${textArea(form, 'description', 'Description')}
        ${this.#categoriesField()}
        <hr class="divider" />
        <moz-checkbox
          label="Experimental"
          ?checked=${form.value('is_experimental')}
          @change=${(e: Event) =>
            form.set('is_experimental', (e.target as HTMLInputElement).checked)}
        ></moz-checkbox>
        <moz-checkbox
          label="This add-on requires payment, non-free services or software, or additional hardware"
          ?checked=${form.value('requires_payment')}
          @change=${(e: Event) =>
            form.set(
              'requires_payment',
              (e.target as HTMLInputElement).checked,
            )}
        ></moz-checkbox>
        ${this.#policyField({
          label: 'This add-on has an End-User License Agreement',
          hasKey: 'has_eula',
          textKey: 'eula',
        })}
        ${this.#policyField({
          label: 'This add-on has a Privacy Policy',
          hasKey: 'has_privacy_policy',
          textKey: 'privacy_policy',
        })}
      </div>
    `;
  }

  #categoriesField() {
    const choices = this.#categoryChoices();
    const selected = this.#form.value('categories') ?? [];
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
    hasKey: 'has_eula' | 'has_privacy_policy';
    textKey: 'eula' | 'privacy_policy';
  }) {
    const form = this.#form;
    const checked = Boolean(form.value(opts.hasKey));
    return html`<div class="policy">
      <moz-checkbox
        label=${opts.label}
        ?checked=${checked}
        @change=${(e: Event) =>
          form.set(opts.hasKey, (e.target as HTMLInputElement).checked)}
      ></moz-checkbox>
      ${checked ? textArea(form, opts.textKey, opts.label) : nothing}
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
          this.#form,
          () => this.#startEdit(),
          () => this.#save(),
        ),
      )}
      ${this.#form.editing ? this.#editForm() : this.#view(this.addon)}
    </moz-card>`;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'listing-details-card': ListingDetailsCard;
  }
}
