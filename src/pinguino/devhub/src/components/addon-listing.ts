import type { IconName, InputType } from '@mozilla/acorn-web-components';
import {
  html,
  LitElement,
  nothing,
  type PropertyValues,
  type TemplateResult,
  unsafeCSS,
} from 'lit';
import { customElement, property, state } from 'lit/decorators.js';
import {
  type Addon,
  type AddonAuthor,
  type AddonAuthorRole,
  type AddonListingEdit,
  type AddonScreenshot,
  authorsQuery,
  categoriesQuery,
  createPreview,
  fetchEulaPolicy,
  pendingAuthorsQuery,
  removePreview,
  updateAddon,
  updateAuthor,
  updateEulaPolicy,
  updateIcon,
  updatePreview,
} from '../data';
import styles from './addon-listing.css?inline';

const MAX_CATEGORIES = 3;

// The edit draft: the main listing fields plus the EULA/privacy text, which are
// saved through a separate endpoint.
type ListingDraft = AddonListingEdit & {
  hasEula?: boolean;
  eula?: string;
  hasPrivacyPolicy?: boolean;
  privacyPolicy?: string;
};

type SectionId =
  | 'listing-details'
  | 'graphic-assets'
  | 'authors'
  | 'technical-details';

type SectionInfo = {
  id: SectionId;
  title: string;
  description: string;
  icon: IconName;
};

// One editable authors row. Existing authors carry their real user id/email;
// `isNew` rows are added in this edit session and collect a user id to invite
// (the pending-authors API resolves people by numeric id, not email).
type AuthorDraft = {
  userId: number;
  name: string;
  email: string;
  role: AddonAuthorRole;
  listed: boolean;
  isNew?: boolean;
};

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

// Keyed by id so each card can look up its own metadata with a total,
// non-optional access; SECTIONS is the ordered list the nav renders.
const SECTION = {
  // TODO: "applied-policy" matches design, but acorn UX might not be happy
  'listing-details': {
    id: 'listing-details',
    title: 'Listing details',
    icon: 'applied-policy',
    description:
      'Describe your listing, categories, and promotional assets on AMO.',
  },
  'graphic-assets': {
    id: 'graphic-assets',
    title: 'Graphical assets',
    icon: 'canvas',
    description: 'The icon, banner, and screenshots shown on your listing.',
  },
  authors: {
    id: 'authors',
    title: 'Authors',
    icon: 'users',
    description: 'Developers with permission to manage this add-on.',
  },
  'technical-details': {
    id: 'technical-details',
    title: 'Technical details',
    icon: 'layer',
    description: 'Developer notes and metadata for this add-on.',
  },
} satisfies Record<SectionId, SectionInfo>;

const SECTIONS: SectionInfo[] = Object.values(SECTION);

@customElement('addon-listing')
export class AddonListing extends LitElement {
  @property({ attribute: false }) addon!: Addon;
  // Which section (card) to show; each is its own page under the edit tab.
  @property() section: string = SECTIONS[0].id;

  @state() private editing = false;
  @state() private saving = false;
  @state() private error = '';
  @state() private draft: ListingDraft = {};

  #categories = categoriesQuery(this);
  #authors = authorsQuery(this, () => this.addon?.slug ?? '');
  #pending = pendingAuthorsQuery(this, () => this.addon?.slug ?? '');
  // Original EULA/privacy text, fetched on edit open, to diff against on save.
  #eulaBaseline = { eula: '', privacyPolicy: '' };
  // Batched authors editor: the working rows and the pre-edit baseline, to diff
  // role changes on save.
  @state() private authorsDraft: AuthorDraft[] = [];
  #authorsBaseline = new Map<number, { role: AddonAuthorRole }>();
  // In-progress screenshot caption edits, keyed by preview id.
  @state() private captionDrafts: Record<number, string> = {};

  static styles = unsafeCSS(styles);

  // The section is a route (its own page), so leaving one drops any unsaved
  // edit state from the previous section.
  willUpdate(changed: PropertyValues<this>) {
    if (changed.has('section')) this.editing = false;
  }

  get #activeSection(): SectionId {
    return this.section in SECTION
      ? (this.section as SectionId)
      : SECTIONS[0].id;
  }

  // Renders the heading for a section's card from its SECTION metadata.
  // `actions` overrides the default (inert) Edit button; cards pass their Edit
  // or Save/Cancel controls.
  #cardHead(id: SectionId, actions?: TemplateResult) {
    const { title, description, icon } = SECTION[id];
    return html`<div slot="heading" class="card-head">
      <div>
        <span class="card-title">
          <moz-icon name=${icon}></moz-icon>
          <h2>${title}</h2>
        </span>
        <p class="sub">${description}</p>
      </div>
      ${actions ?? html`<moz-button size="small">Edit</moz-button>`}
    </div>`;
  }

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
      developerComments: a.developerComments ?? '',
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
    if ((d.developerComments ?? '') !== (a.developerComments ?? ''))
      out.developerComments = d.developerComments;
    if ((d.experimental ?? false) !== (a.flags?.experimental ?? false))
      out.experimental = d.experimental;
    if ((d.requiresPayment ?? false) !== (a.flags?.requiresPayment ?? false))
      out.requiresPayment = d.requiresPayment;
    return out;
  }

  // Runs a one-off graphic-assets action (icon/screenshot upload, screenshot
  // removal) that persists immediately, toggling saving/error around it.
  #runAction(fn: () => Promise<unknown>) {
    this.saving = true;
    this.error = '';
    fn()
      .catch((e) => {
        this.error = e instanceof Error ? e.message : 'Action failed.';
      })
      .finally(() => {
        this.saving = false;
      });
  }

  // --- Authors: a batched editor (Save/Cancel), unlike the immediate uploads ---

  #startAuthorsEdit() {
    const authors = this.#authors().data ?? [];
    this.authorsDraft = authors.map((au) => ({
      userId: au.userId ?? 0,
      name: au.name,
      email: au.email ?? '',
      role: au.role ?? 'developer',
      listed: au.listed ?? true,
    }));
    this.#authorsBaseline = new Map(
      this.authorsDraft.map((r) => [r.userId, { role: r.role }]),
    );
    this.error = '';
    this.editing = true;
  }

  #setAuthor(index: number, patch: Partial<AuthorDraft>) {
    this.authorsDraft = this.authorsDraft.map((r, i) =>
      i === index ? { ...r, ...patch } : r,
    );
  }

  #addDraftAuthor() {
    this.authorsDraft = [
      ...this.authorsDraft,
      {
        userId: 0,
        name: '',
        email: '',
        role: 'developer',
        listed: true,
        isNew: true,
      },
    ];
  }

  // Diff the draft against the pre-edit baseline and PATCH role changes.
  // New authors are invited by email in prod; the v5 API has no session-usable
  // email->user_id lookup, so new rows aren't wired yet.
  async #saveAuthors() {
    const slug = this.addon.slug;
    this.saving = true;
    this.error = '';
    try {
      for (const r of this.authorsDraft) {
        if (r.isNew) continue; // TODO: invite by email once the API supports it
        const base = this.#authorsBaseline.get(r.userId);
        if (base && r.role !== base.role) {
          await updateAuthor(slug, r.userId, { role: r.role });
        }
      }
      this.editing = false;
    } catch (e) {
      this.error = e instanceof Error ? e.message : 'Could not save authors.';
    } finally {
      this.saving = false;
    }
  }

  // moz-input-file exposes the selection as a File[] (native inputs a FileList);
  // both index the same way.
  #firstFile(e: Event): File | undefined {
    const target = e.target as { files?: ArrayLike<File> | null };
    return target.files?.[0];
  }

  #onIcon(e: Event) {
    const file = this.#firstFile(e);
    if (file) this.#runAction(() => updateIcon(this.addon.slug, file));
  }

  #onScreenshot(e: Event) {
    const file = this.#firstFile(e);
    if (file) this.#runAction(() => createPreview(this.addon.slug, file));
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

  #textArea(
    label: string,
    key: 'summary' | 'description' | 'developerComments',
  ) {
    return html`<moz-textarea
      label=${label}
      .value=${this.draft[key] ?? ''}
      full-width
      @input=${(e: Event) =>
        this.#set(key, (e.target as HTMLTextAreaElement).value)}
    ></moz-textarea>`;
  }

  #listingForm() {
    const d = this.draft;
    return html`
      <div class="form">
        ${
          this.error
            ? html`<moz-message-bar type="error">${this.error}</moz-message-bar>`
            : nothing
        }
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
                this.#set(
                  opts.textKey,
                  (e.target as HTMLTextAreaElement).value,
                )}
            ></moz-textarea>`
          : nothing
      }
    </div>`;
  }

  #listingView(a: Addon) {
    const flags = a.flags ?? {};
    return html`
      <dl>
        ${this.#row('Add-on name', a.name)}
        ${this.#row('Add-on URL', this.#link(a.listingUrl))}
        ${this.#row('Homepage of the add-on', this.#link(a.homepageUrl))}
        ${this.#row('Support Website', this.#link(a.supportUrl))}
        ${this.#row('Support Email', a.supportEmail)}
        ${this.#row('Summary', a.summary)}
        ${this.#row('Description', a.description)}
        ${this.#row(
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

  // Edit / Save+Cancel for cards backed by the draft + #save (listing, technical).
  #draftActions() {
    return this.editing
      ? html`<div class="card-actions">
          <moz-button
            size="small"
            variant="ghost"
            ?disabled=${this.saving}
            @click=${() => {
              this.editing = false;
            }}
            >Cancel</moz-button
          >
          <moz-button
            size="small"
            variant="primary"
            ?disabled=${this.saving}
            @click=${() => this.#save()}
            >${this.saving ? 'Saving…' : 'Save'}</moz-button
          >
        </div>`
      : html`<moz-button size="small" @click=${() => this.#startEdit()}
          >Edit</moz-button
        >`;
  }

  // Edit / Save+Cancel for the graphic-assets card. Caption edits are batched
  // and persisted on Save; icon/screenshot uploads stay immediate (a file
  // picker commits as soon as a file is chosen).
  #graphicsActions() {
    return this.editing
      ? html`<div class="card-actions">
          <moz-button
            size="small"
            variant="ghost"
            ?disabled=${this.saving}
            @click=${() => {
              this.editing = false;
              this.captionDrafts = {};
            }}
            >Cancel</moz-button
          >
          <moz-button
            size="small"
            variant="primary"
            ?disabled=${this.saving}
            @click=${() => this.#saveGraphics()}
            >${this.saving ? 'Saving…' : 'Save'}</moz-button
          >
        </div>`
      : html`<moz-button size="small" @click=${() => this.#startGraphicsEdit()}
          >Edit</moz-button
        >`;
  }

  #startGraphicsEdit() {
    this.captionDrafts = {};
    this.error = '';
    this.editing = true;
  }

  // Persist the screenshot captions the user changed, then leave edit mode.
  async #saveGraphics() {
    const slug = this.addon.slug;
    this.saving = true;
    this.error = '';
    try {
      for (const s of this.addon.screenshots ?? []) {
        if (s.id == null) continue;
        const draft = this.captionDrafts[s.id];
        if (draft !== undefined && draft !== (s.caption ?? '')) {
          await updatePreview(slug, s.id, draft);
        }
      }
      this.editing = false;
      this.captionDrafts = {};
    } catch (e) {
      this.error = e instanceof Error ? e.message : 'Could not save changes.';
    } finally {
      this.saving = false;
    }
  }

  #listingCard() {
    return html`<moz-card
      appearance="outline"
      spacing="spacious"
      id="listing-details"
    >
      ${this.#cardHead('listing-details', this.#draftActions())}
      ${this.editing ? this.#listingForm() : this.#listingView(this.addon)}
    </moz-card>`;
  }

  #roleSelect(value: AddonAuthorRole, onChange: (r: AddonAuthorRole) => void) {
    return html`<moz-select
      label="Role"
      class="role-select"
      .value=${value}
      @change=${(e: Event) =>
        onChange((e.target as HTMLSelectElement).value as AddonAuthorRole)}
    >
      <moz-option value="developer" label="Developer"></moz-option>
      <moz-option value="owner" label="Owner"></moz-option>
    </moz-select>`;
  }

  // One screenshot row: thumbnail on the left, caption on the right — read-only
  // text when viewing, a labelled textarea when editing. Caption edits are held
  // in captionDrafts and saved by the card's Save button.
  #screenshotShot(a: Addon, s: AddonScreenshot) {
    const id = s.id;
    if (!this.editing) {
      return html`<div class="shot">
        <img src=${s.src} alt=${s.caption ?? ''} />
        <div class="shot-body">
          <p class="shot-caption ${s.caption ? '' : 'muted'}">
            ${s.caption || 'No caption'}
          </p>
        </div>
      </div>`;
    }
    const caption =
      id != null ? (this.captionDrafts[id] ?? s.caption ?? '') : '';
    return html`<div class="shot">
      <img src=${s.src} alt=${s.caption ?? ''} />
      <div class="shot-body">
        <p class="caption-label">
          Please provide a caption for this screenshot:
          <span class="locale-badge">English (US)</span>
        </p>
        <moz-textarea
          aria-label="Caption"
          placeholder="Text"
          full-width
          ?disabled=${id == null}
          .value=${caption}
          @input=${(e: Event) => {
            if (id == null) return;
            this.captionDrafts = {
              ...this.captionDrafts,
              [id]: (e.target as HTMLTextAreaElement).value,
            };
          }}
        ></moz-textarea>
        ${
          id != null
            ? html`<moz-button
                class="shot-remove"
                size="small"
                variant="ghost"
                ?disabled=${this.saving}
                @click=${() => this.#runAction(() => removePreview(a.slug, id))}
                >Remove screenshot</moz-button
              >`
            : nothing
        }
      </div>
    </div>`;
  }

  #graphicAssetsCard(a: Addon) {
    const shots = a.screenshots ?? [];
    return html`<moz-card
      appearance="outline"
      spacing="spacious"
      id="graphic-assets"
    >
      ${this.#cardHead('graphic-assets', this.#graphicsActions())}
      <div class="asset">
        <p class="label">Upload an icon</p>
        <p class="help">
          You can upload PNG or JPG files. If your icon's bigger than 128×128
          pixels, we'll resize it for you. It will also scale to three sizes:
          32×32px, 64×64px, 128×128px.
        </p>
        <div class="icon-sizes">
          ${[32, 64, 128].map((px) => this.#iconBox(px))}
        </div>
        ${
          this.editing
            ? html`<moz-input-file
                accept="image/png,image/jpeg"
                label="Upload icon"
                ?disabled=${this.saving}
                @change=${(e: Event) => this.#onIcon(e)}
              ></moz-input-file>`
            : nothing
        }
      </div>
      <!-- Banner/hero assets are in the design but have no AMO API for
           extensions yet, so that section is omitted. -->
      <div class="asset">
        <p class="label">Screenshots</p>
        <p class="help">
          We support PNG and JPG, but PNG is best. Screenshots should be up to
          2400×1800 pixels. Adding screenshots to your product page really boosts
          the chances people will install it.
        </p>
        ${
          shots.length
            ? html`<div class="shots">
                ${shots.map((s) => this.#screenshotShot(a, s))}
              </div>`
            : html`<p class="muted">No screenshots uploaded yet.</p>`
        }
        ${
          this.editing
            ? html`<moz-input-file
                accept="image/png,image/jpeg"
                label="Upload screenshot"
                ?disabled=${this.saving}
                @change=${(e: Event) => this.#onScreenshot(e)}
              ></moz-input-file>`
            : nothing
        }
      </div>
      ${
        this.error
          ? html`<moz-message-bar type="error">${this.error}</moz-message-bar>`
          : nothing
      }
    </moz-card>`;
  }

  // Edit toggle when viewing; "+ Add new author" / Cancel / Save when editing.
  #authorsActions() {
    if (!this.editing) {
      return html`<moz-button size="small" @click=${() =>
        this.#startAuthorsEdit()}
        >Edit</moz-button
      >`;
    }
    return html`<div class="card-actions">
      <moz-button
        size="small"
        variant="ghost"
        icon-start="add"
        ?disabled=${this.saving}
        @click=${() => this.#addDraftAuthor()}
        >Add new author</moz-button
      >
      <moz-button
        size="small"
        variant="ghost"
        ?disabled=${this.saving}
        @click=${() => {
          this.editing = false;
        }}
        >Cancel</moz-button
      >
      <moz-button
        size="small"
        variant="primary"
        ?disabled=${this.saving}
        @click=${() => this.#saveAuthors()}
        >${this.saving ? 'Saving…' : 'Save'}</moz-button
      >
    </div>`;
  }

  #authorsCard() {
    const result = this.#authors();
    const authors = result.data ?? [];
    return html`<moz-card appearance="outline" spacing="spacious" id="authors">
      ${this.#cardHead('authors', this.#authorsActions())}
      ${
        this.error
          ? html`<moz-message-bar type="error">${this.error}</moz-message-bar>`
          : nothing
      }
      ${
        result.isPending
          ? html`<p class="muted">Loading authors…</p>`
          : this.editing
            ? html`<div class="authors">
                ${this.authorsDraft.map((r, i) => this.#authorEditRow(i, r))}
              </div>`
            : authors.length
              ? html`<div class="authors">
                  ${authors.map((au) => this.#authorRow(au))}
                </div>`
              : html`<p class="muted">No authors listed.</p>`
      }
      ${this.#pendingGroup()}
    </moz-card>`;
  }

  #roleLabel(role: AddonAuthorRole | undefined): string {
    return role ? role.charAt(0).toUpperCase() + role.slice(1) : '—';
  }

  // View row: email and role, two columns (the listing shows no display name).
  #authorRow(au: AddonAuthor) {
    return html`<div class="author">
      ${this.#row("Author's email", au.email || au.name)}
      ${this.#row('Role', this.#roleLabel(au.role))}
    </div>`;
  }

  // Edit row: email (read-only for existing; an invite field for new rows),
  // a role select, and a "⋯" placeholder. The menu (Remove + visibility) is a
  // TODO; the 3-dot button is inert for now.
  #authorEditRow(index: number, r: AuthorDraft) {
    return html`<div class="author-edit">
      ${
        r.isNew
          ? html`<moz-input-text
              label="Author's email"
              type="email"
              full-width
              .value=${r.email}
              @input=${(e: Event) =>
                this.#setAuthor(index, {
                  email: (e.target as HTMLInputElement).value,
                })}
            ></moz-input-text>`
          : html`<moz-input-text
              label="Author's email"
              full-width
              disabled
              .value=${r.email}
            ></moz-input-text>`
      }
      ${this.#roleSelect(r.role, (role) => this.#setAuthor(index, { role }))}
      <!-- TODO: row overflow menu (Remove + visibility) moz-panel -->
      <moz-button
        class="menu-btn"
        icon-only="Edit"
        icon-start="page-actions"
        variant="ghost"
        ?disabled=${this.saving}
        >
        </moz-button
      >
    </div>`;
  }

  // Authors invited but not yet confirmed, in their own labelled group.
  #pendingGroup() {
    const pending = this.#pending().data ?? [];
    if (!pending.length) return nothing;
    return html`<div class="pending">
      <h3 class="pending-head">
        <span class="dot"></span> Authors pending confirmation
      </h3>
      <div class="authors">
        ${pending.map(
          (au) => html`<div class="author">
            ${this.#row("Author's email", au.email || au.name)}
            ${this.#row('Role', this.#roleLabel(au.role))}
          </div>`,
        )}
      </div>
    </div>`;
  }

  #technicalCard(a: Addon) {
    return html`<moz-card
      appearance="outline"
      spacing="spacious"
      id="technical-details"
    >
      ${this.#cardHead('technical-details', this.#draftActions())}
      ${
        this.editing
          ? html`<div class="form">
              ${
                this.error
                  ? html`<moz-message-bar type="error"
                      >${this.error}</moz-message-bar
                    >`
                  : nothing
              }
              ${this.#textArea('Developer comments', 'developerComments')}
              <dl>
                ${this.#row('UUID', a.uuid)} ${this.#row('Whiteboard', a.whiteboard)}
              </dl>
            </div>`
          : html`<dl>
              ${this.#row('Developer comments', a.developerComments)}
              ${this.#row('UUID', a.uuid)}
              ${this.#row('Whiteboard', a.whiteboard)}
            </dl>`
      }
    </moz-card>`;
  }

  #activeCard(a: Addon) {
    switch (this.#activeSection) {
      case 'graphic-assets':
        return this.#graphicAssetsCard(a);
      case 'authors':
        return this.#authorsCard();
      case 'technical-details':
        return this.#technicalCard(a);
      default:
        return this.#listingCard();
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
              href="/pinguino/addon/${a.slug}/edit/${s.id}"
              icon-start=${s.icon}
              >${s.title}</moz-page-nav-button
            >`,
          )}
        </moz-page-nav>

        <div class="cards">${this.#activeCard(a)}</div>
      </div>
    `;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'addon-listing': AddonListing;
  }
}
