import { html, nothing } from 'lit';
import { customElement, state } from 'lit/decorators.js';
import {
  type AddonAuthor,
  type AddonAuthorRole,
  authorsQuery,
  pendingAuthorsQuery,
  updateAuthor,
} from '../../data';
import { SectionCard } from './section-card';

// One editable authors row. Existing authors carry their real user id/email;
// `isNew` rows are added in this edit session and collect an email to invite
// (the pending-authors API needs a numeric id, so new rows aren't wired yet).
type AuthorDraft = {
  userId: number;
  name: string;
  email: string;
  role: AddonAuthorRole;
  listed: boolean;
  isNew?: boolean;
};

@customElement('authors-card')
export class AuthorsCard extends SectionCard {
  #authors = authorsQuery(this, () => this.addon?.slug ?? '');
  #pending = pendingAuthorsQuery(this, () => this.addon?.slug ?? '');
  // Batched authors editor: the working rows and the pre-edit baseline, to diff
  // role changes on save.
  @state() private draft: AuthorDraft[] = [];
  #baseline = new Map<number, { role: AddonAuthorRole }>();

  #startEdit() {
    const authors = this.#authors().data ?? [];
    this.draft = authors.map((au) => ({
      userId: au.userId ?? 0,
      name: au.name,
      email: au.email ?? '',
      role: au.role ?? 'developer',
      listed: au.listed ?? true,
    }));
    this.#baseline = new Map(
      this.draft.map((r) => [r.userId, { role: r.role }]),
    );
    this.error = '';
    this.editing = true;
  }

  #setAuthor(index: number, patch: Partial<AuthorDraft>) {
    this.draft = this.draft.map((r, i) =>
      i === index ? { ...r, ...patch } : r,
    );
  }

  #addDraftAuthor() {
    this.draft = [
      ...this.draft,
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
  async #save() {
    const slug = this.addon.slug;
    this.saving = true;
    this.error = '';
    try {
      for (const r of this.draft) {
        if (r.isNew) continue; // TODO: invite by email once the API supports it
        const base = this.#baseline.get(r.userId);
        if (base && r.role !== base.role) {
          await updateAuthor(slug, r.userId, { role: r.role });
        }
      }
      this.editing = false;
    } catch (e) {
      this.setError(e);
    } finally {
      this.saving = false;
    }
  }

  // Edit toggle when viewing; "Add new author" / Cancel / Save when editing.
  #actions() {
    if (!this.editing) {
      return html`<moz-button size="small" @click=${() => this.#startEdit()}
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
        @click=${() => this.#save()}
        >${this.saving ? 'Saving…' : 'Save'}</moz-button
      >
    </div>`;
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

  #roleLabel(role: AddonAuthorRole | undefined): string {
    return role ? role.charAt(0).toUpperCase() + role.slice(1) : '—';
  }

  // View row: email and role, two columns (the listing shows no display name).
  #row(au: AddonAuthor) {
    return html`<div class="author">
      ${this.row("Author's email", au.email || au.name)}
      ${this.row('Role', this.#roleLabel(au.role))}
    </div>`;
  }

  // Edit row: email (read-only for existing; an invite field for new rows),
  // a role select, and a "⋯" placeholder. The menu (Remove + visibility) is a
  // TODO; the 3-dot button is inert for now.
  #editRow(index: number, r: AuthorDraft) {
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
      </moz-button>
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
            ${this.row("Author's email", au.email || au.name)}
            ${this.row('Role', this.#roleLabel(au.role))}
          </div>`,
        )}
      </div>
    </div>`;
  }

  render() {
    const result = this.#authors();
    const authors = result.data ?? [];
    return html`<moz-card appearance="outline" spacing="spacious" id="authors">
      ${this.cardHead('authors', this.#actions())} ${this.errorBar()}
      ${
        result.isPending
          ? html`<p class="muted">Loading authors…</p>`
          : this.editing
            ? html`<div class="authors">
              ${this.draft.map((r, i) => this.#editRow(i, r))}
            </div>`
            : authors.length
              ? html`<div class="authors">
                ${authors.map((au) => this.#row(au))}
              </div>`
              : html`<p class="muted">No authors listed.</p>`
      }
      ${this.#pendingGroup()}
    </moz-card>`;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'authors-card': AuthorsCard;
  }
}
