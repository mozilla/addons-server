import { html, nothing } from 'lit';
import { customElement } from 'lit/decorators.js';
import { unsafeHTML } from 'lit/directives/unsafe-html.js';
import {
  type Addon,
  type AddonListingEdit,
  categoriesQuery,
  type EulaPolicyEdit,
  eulaPolicyQuery,
  fetchEulaPolicy,
  updateAddon,
  updateEulaPolicy,
} from '../../data';
import { FormController, textArea, textField } from '../../foundations/form';
import { MARKDOWN_TAGS, sanitizeHTML } from '../../utils/sanitizeHTML';
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
  // Policy text for the view-mode preview; only fetched when the add-on has one.
  #eula = eulaPolicyQuery(
    this,
    () => this.addon?.slug ?? '',
    () =>
      Boolean(
        this.addon?.flags?.hasEula || this.addon?.flags?.hasPrivacyPolicy,
      ),
  );
  // Original EULA/privacy text, fetched on edit open, to diff against on save.
  #eulaBaseline = { eula: '', privacyPolicy: '' };

  #startEdit() {
    const a = this.addon;
    this.#form.start({
      name: a.name,
      slug: a.slug,
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
      ...(d.slug !== a.slug && { slug: d.slug }),
      ...((d.summary ?? '') !== (a.summary ?? '') && { summary: d.summary }),
      ...((d.description ?? '') !== (a.description ?? '') && {
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

  #save() {
    const previousSlug = this.addon.slug;
    return this.#form.submit(async (d) => {
      const listing = this.#changedListing(d);
      const eula = this.#changedEula(d);
      if (Object.keys(listing).length) {
        await updateAddon(this.addon.slug, listing);
      }
      if (eula) {
        await updateEulaPolicy(this.addon.slug, eula);
      }
      // The slug lives in the page URL, so a changed slug leaves the current
      // URL pointing at a now-missing add-on. Point the router at the new slug
      // (the add-on list has already refetched via updateAddon).
      if (listing.slug && listing.slug !== previousSlug) {
        history.pushState(
          {},
          '',
          location.pathname.replace(
            `/addon/${previousSlug}`,
            `/addon/${listing.slug}`,
          ),
        );
        dispatchEvent(new PopStateEvent('popstate'));
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

  // "Add-on URL" edit: the listing-URL base shown as static text with the slug
  // input inline beside it. The base is the add-on's listing URL minus its
  // current slug (its last path segment), so the host/locale aren't hard-coded.
  #urlField() {
    const form = this.#form;
    const base = (this.addon.listingUrl ?? '')
      .replace(/\/?$/, '')
      .replace(/[^/]*$/, '');
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
          @input=${(e: Event) =>
            form.set('slug', (e.target as HTMLInputElement).value)}
        ></moz-input-text>
      </div>
    </div>`;
  }

  #editForm() {
    const form = this.#form;
    return html`
      <div class="form">
        ${this.errorBar(form.error)}
        ${textField(form, 'name', 'Add-on name')}
        ${this.#urlField()}
        ${textField(form, 'homepage', 'Homepage of the add-on', 'url')}
        ${textField(form, 'support_url', 'Support Website', 'url')}
        ${textField(form, 'support_email', 'Support Email', 'email')}
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
        ${this.row('Add-on URL', this.link(a.listingUrl))}
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
      </dl>
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
