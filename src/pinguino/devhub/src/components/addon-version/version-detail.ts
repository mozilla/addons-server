import {
  css,
  html,
  nothing,
  type PropertyValues,
  type TemplateResult,
} from 'lit';
import { customElement, property, state } from 'lit/decorators.js';
import { unsafeHTML } from 'lit/directives/unsafe-html.js';
import { BASE, MAX_UPLOAD_SIZE, SOURCE_EXTENSIONS } from '../../base';
import {
  type ActivityPage,
  activityInfiniteQuery,
  appVersionsQuery,
  disableVersion,
  localized,
  removeVersion,
  replyToVersion,
  type Update,
  updateVersion,
  updateVersionLicense,
  type Version,
  type VersionEdit,
  versionQuery,
} from '../../data';
import { errorStatus } from '../../data/http';
import '../../foundations/badges';
import '../../foundations/infinite-list';
import {
  timelineStep,
  timelineStyles,
} from '../../foundations/components/timeline';
import {
  FieldError,
  FormController,
  textArea,
  textField,
} from '../../foundations/form';
import { panelPointer } from '../../foundations/panel';
import { setPageTitle } from '../../page-title';
import { navigateTo } from '../../utils/helper';
import { ACTIVITY_TAGS, sanitizeHTML } from '../../utils/sanitizeHTML';
import {
  customLicenseErrors,
  type LicenseDraft,
  licenseChanged,
  licenseDraft,
  licenseEdit,
  licenseField,
  licenseUrl,
  routeVersionErrors,
} from '../addon-listing/license';
import { SectionCard, sharedStyles } from '../addon-listing/section-card';
import '../addon-manage-header';
import '../error-page';
import './chat-card';
import androidLogo from '../../static/img/android.svg';

type CompatRow = { app: string; min: string; max: string; isNew?: boolean };
type Tab = 'details' | 'activity';
type VersionDraft = VersionEdit & LicenseDraft;

const APP_NAMES: Record<string, string> = {
  firefox: 'Firefox',
  android: 'Firefox for Android',
};

const APP_ICONS: Record<string, TemplateResult> = {
  firefox: html`<moz-icon
      name=${'logo-firefox'}
      title=${name}
      aria-label=${name}
    ></moz-icon>`,
  android: html`<img src=${androidLogo}/>`,
};

@customElement('version-detail')
export class VersionDetail extends SectionCard {
  @property({ type: Number }) versionId = 0;

  @state() private tab: Tab = 'details';
  @state() private compat: CompatRow[] = [];
  // A File replaces the attached source, null removes it on save.
  @state() private source?: File | null;
  @state() private confirmingDelete = false;

  #version = versionQuery(
    this,
    () => this.addon?.slug ?? '',
    () => this.versionId,
  );

  #activity = activityInfiniteQuery(
    this,
    () => this.addon?.slug ?? '',
    () => this.versionId,
  );

  // Version details
  #form = new FormController<VersionDraft>(this);
  #appVersions = Object.fromEntries(
    Object.keys(APP_NAMES).map((app) => [
      app,
      appVersionsQuery(this, () =>
        this.compat.some((r) => r.app === app) ? app : undefined,
      ),
    ]),
  );

  // Version activity
  #reply = new FormController<{ comments: string }>(this);

  static styles = [
    sharedStyles,
    panelPointer,
    timelineStyles,
    css`
      @media (max-width: 900px) {
        .main-content {
          flex-direction: column-reverse;
        }
      }
      .main-content {
        display: flex;
        gap: var(--space-medium);
        padding: var(--space-large) 0;
      }
      .version-content {
        flex-basis: 75%;
      }
      .version-head {
        display: flex;
        flex-direction: column;
        gap: var(--card-gap);
      }
      .timeline {
        --marker-size: 22px;
        --timeline-inset: 0px;
        max-width: 340px;
      }
      .submission-log .card-head {
        margin: 0;
      }
      /* Applications */
      .entries{
        display: flex;
        flex-direction: column;
        gap: var(--space-small);
        padding: var(--space-small);
      }
      .entry {
        display: flex;
        align-items: end;
        gap: var(--space-medium);
      }
      .entry .app-icon > * {
        height: 100%;
        width: 20px;
      }
      /* Details */
      moz-input-file {
        width: 100%;
      }
      .delete-source {
        display: flex;
        justify-content: end;
        white-space: pre;
        padding: var(--space-small);
      }
      .link-button {
        color: var(--link-color, LinkText);
        text-decoration: underline;
        cursor: pointer;
      }
      /* Notifications */
      .activities {
        height: 600px;
        margin-block: var(--space-medium);
        --infinite-list-gap: var(--space-medium);
      }
      .reply {
        display: flex;
        align-items: end;
        gap: var(--space-small);
        background-color: var(--background-color-canvas);
        border-radius: var(--border-radius-xlarge);
        padding: var(--space-small);
      }
      .reply > moz-input-text::part(wrapper) {
        gap: 0;
      }
      .reply > moz-input-text::part(field) {
        border: none;
        background: none;
      }
    `,
  ];

  willUpdate(changed: PropertyValues<this>) {
    if (changed.has('versionId')) this.#cancel();
  }

  #scrollToNewest() {
    this.renderRoot.querySelector('app-infinite-list')?.scrollToStart();
  }

  updated(changed: PropertyValues<this>) {
    const v = this.#version().data;
    if (v) setPageTitle(`Version ${v.version}`, this.addon.name);
    if (changed.has('versionId')) this.#scrollToNewest();
  }

  #startEdit(v: Version) {
    this.compat = Object.entries(v.compatibility ?? {}).map(
      ([app, { min, max }]) => ({ app, min, max }),
    );
    this.source = undefined;
    this.#form.start({
      release_notes: localized(v.release_notes),
      approval_notes: v.approval_notes ?? '',
      ...licenseDraft(v.license),
    });
  }

  #cancel() {
    this.#form.cancel();
    this.source = undefined;
  }

  #edit(draft: VersionEdit, v: Version): VersionEdit {
    const saved = v.compatibility ?? {};
    const compatChanged =
      this.compat.length !== Object.keys(saved).length ||
      this.compat.some(
        (r) => r.min !== saved[r.app]?.min || r.max !== saved[r.app]?.max,
      );
    return {
      ...(draft.release_notes !== localized(v.release_notes) && {
        release_notes: draft.release_notes,
      }),
      ...(draft.approval_notes !== (v.approval_notes ?? '') && {
        approval_notes: draft.approval_notes,
      }),
      ...(compatChanged && {
        compatibility: Object.fromEntries(
          this.compat.map((r) => [
            r.app,
            { ...(r.min && { min: r.min }), ...(r.max && { max: r.max }) },
          ]),
        ),
      }),
    };
  }

  #licenseEdit(d: VersionDraft, v: Version) {
    if (!licenseChanged(d, licenseDraft(v.license))) return undefined;
    const errors = customLicenseErrors(d);
    if (Object.keys(errors).length) throw new FieldError(errors);
    return licenseEdit(d);
  }

  #save(v: Version) {
    return this.#form.submit(async (draft) => {
      const license = this.#licenseEdit(draft, v);
      const { slug } = this.addon;
      await updateVersion(slug, v.id, this.#edit(draft, v), this.source);
      this.source = undefined;
      if (license) {
        await updateVersionLicense(
          slug,
          v.id,
          license.license,
          license.custom_license,
        ).catch((e: unknown) => {
          throw routeVersionErrors(e);
        });
      }
    });
  }

  get #unusedApps() {
    return Object.keys(APP_NAMES).filter(
      (app) => !this.compat.some((r) => r.app === app),
    );
  }

  #setCompat(index: number, patch: Partial<CompatRow>) {
    this.compat = this.compat.map((r, i) =>
      i === index ? { ...r, ...patch } : r,
    );
  }

  #sendReply(v: Version) {
    const comments = this.#reply.value('comments')?.trim();
    if (!comments) return;
    return this.#reply.submit(async () => {
      await replyToVersion(this.addon.slug, v.id, comments);
      this.#reply.set('comments', '');
      this.#scrollToNewest();
    });
  }

  #menu(v: Version) {
    return html`
      <moz-button
        variant="ghost"
        icon-start="page-actions"
        icon-only="Version actions"
        menu-id='version-actions'
        ?disabled=${this.saving}
      ></moz-button>
      <moz-panel-list id='version-actions' type="menu" label="Version actions">
        <moz-panel-item
          icon-start="delete"
          @click=${() => {
            this.error = '';
            this.confirmingDelete = true;
          }}
          >Delete version</moz-panel-item
        >
        <moz-panel-item
          icon-start=${v.is_disabled ? 'play-fill' : 'block'}
          @click=${() =>
            this.runAction(() =>
              v.is_disabled
                ? updateVersion(this.addon.slug, v.id, { is_disabled: false })
                : disableVersion(this.addon.slug, v.id),
            )}
          >${v.is_disabled ? 'Reactivate version' : 'Deactivate version'}</moz-panel-item
        >
        <moz-panel-item
          icon-start="downloads"
          @click=${() => window.location.assign(v.file.url)}
          >Download file</moz-panel-item
        >
      </moz-panel-list>
    `;
  }

  #deleteDialog(v: Version) {
    const isCurrent = this.addon.currentVersion?.id === v.id;
    return html`<moz-dialog
      variant="modal"
      dismissable
      heading="Delete version ${v.version}?"
      ?open=${this.confirmingDelete}
      @moz-dialog:dismiss=${() => {
        this.confirmingDelete = false;
      }}
    >
      ${
        isCurrent
          ? html`<p>
              This is the current version of your add-on. Deleting it may change
              your add-on's status, or hide your listing if it's the only public
              version.
            </p>`
          : nothing
      }
      <p>
        Once deleted, you can't upload a new version with the same version
        number.
      </p>
      ${this.errorBar()}
      <moz-button slot="actions" data-dismiss ?disabled=${this.saving}
        >Cancel</moz-button
      >
      <moz-button
        slot="actions"
        variant="destructive"
        ?disabled=${this.saving}
        @click=${() =>
          this.runAction(async () => {
            await removeVersion(this.addon.slug, v.id);
            this.confirmingDelete = false;
            navigateTo(`${BASE}/addon/${this.addon.slug}/versions`);
          })}
        >Delete version</moz-button
      >
    </moz-dialog>`;
  }

  #logPage?: ActivityPage;
  #logSteps: TemplateResult[] = [];

  #submissionLog() {
    const page = this.#activity().data?.pages[0];
    if (page !== this.#logPage) {
      this.#logPage = page;
      this.#logSteps = [...(page?.items ?? [])].slice(0, 3).map((item) =>
        timelineStep(
          html`
            <!-- TODO: The activity API does not expose the type of the activity. -->
            <moz-status-dot
                    icon
                    type=${'information'}
                  ></moz-status-dot>`,
          html`<div>
                    <span>${unsafeHTML(sanitizeHTML(item.title, ACTIVITY_TAGS))}</span>
                    ${
                      item.message
                        ? html`<p class="muted message">
                            ${unsafeHTML(sanitizeHTML(item.message, ACTIVITY_TAGS))}
                          </p>`
                        : nothing
                    }
                    <span class="muted date">${item.date}</span>
                  </div>`,
        ),
      );
    }
    return html`<moz-card class="submission-log" appearance="outline" spacing="spacious">
      ${this.cardHead({ title: 'Submission log' }, html``)}
      ${
        this.#logSteps.length
          ? html`<ol class="timeline log">${this.#logSteps}</ol>`
          : html`<p class="muted">No activity yet.</p>`
      }
    </moz-card>`;
  }

  #appIcon(app: string) {
    return html`<div class="app-icon">${APP_ICONS[app] ?? nothing}</div>`;
  }

  #versionSelect(
    label: string,
    value: string,
    options: string[],
    allowDefault: boolean | undefined,
    onChange: (value: string) => void,
  ) {
    const form = this.#form;
    const all =
      value && !options.includes(value) ? [value, ...options] : options;
    return html`<moz-select
      full-width
      label=${label}
      .value=${value}
      ?disabled=${!form.editing || form.saving}
      @change=${(e: Event) => onChange((e.target as HTMLSelectElement).value)}
    >
      ${
        allowDefault
          ? html`<moz-option value="" label="Default"></moz-option>`
          : nothing
      }
      ${all.map((o) => html`<moz-option value=${o} label=${o}></moz-option>`)}
    </moz-select>`;
  }

  #compat(v: Version) {
    const form = this.#form;
    const rows: CompatRow[] = form.editing
      ? this.compat
      : Object.entries(v.compatibility ?? {}).map(([app, { min, max }]) => ({
          app,
          min,
          max,
        }));
    if (!rows.length && !form.editing) {
      return html`<p class="muted">No compatible applications.</p>`;
    }
    const [next] = form.editing ? this.#unusedApps : [];
    const error = form.fieldError('compatibility');
    return html`<div class="entries">
      ${rows.map((r, i) => {
        const versions = this.#appVersions[r.app]?.().data ?? [];
        return html`<div class="entry">
          ${this.#appIcon(r.app)}
          ${this.#versionSelect(
            'From',
            r.min,
            versions.filter((ver) => !ver.includes('*')),
            r.isNew,
            (min) => this.#setCompat(i, { min }),
          )}
          ${this.#versionSelect('To', r.max, versions, r.isNew, (max) =>
            this.#setCompat(i, { max }),
          )}
          ${
            form.editing && rows.length > 1
              ? html`<moz-button
                  class="menu-btn"
                  variant="ghost"
                  icon-start="delete"
                  icon-only="Remove ${APP_NAMES[r.app] ?? r.app}"
                  ?disabled=${form.saving}
                  @click=${() => {
                    this.compat = this.compat.filter((_, j) => j !== i);
                  }}
                ></moz-button>`
              : nothing
          }
        </div>`;
      })}
      ${
        next
          ? html`<div>
              <a
                class="link-button"
                ?disabled=${form.saving}
                @click=${() => {
                  this.compat = [
                    ...this.compat,
                    { app: next, min: '', max: '', isNew: true },
                  ];
                }}
              >
                Add another application
              </a>
            </div>`
          : nothing
      }
      ${error ? html`<p class="error">${error}</p>` : nothing}
    </div>`;
  }

  #license(v: Version) {
    if (this.#form.editing) {
      return licenseField(this.#form, this.addon.kind === 'theme');
    }
    if (!v.license) return null;
    const name = localized(v.license.name);
    const url = licenseUrl(v.license.slug);
    return url
      ? html`${name}
          <a href=${url} target="_blank" rel="noopener">Details</a>`
      : name;
  }

  #source(v: Version) {
    if (!this.#form.editing) {
      return v.source ? html`<a href=${v.source}>Download source</a>` : null;
    }
    if (v.is_source_editable === false) {
      return html`<moz-message-bar type="warning"
        >You cannot change attached sources because this version has been
        reviewed by Mozilla.</moz-message-bar
      >`;
    }
    if (this.source === null) {
      return html`<p class="muted">
        The current source will be deleted on save.
        <a
          class="link-button"
          ?disabled=${this.#form.saving}
          @click=${() => {
            this.source = undefined;
          }}
          >Undo</a
        >
      </p>`;
    }
    return html`
      <moz-input-file
        accept=${SOURCE_EXTENSIONS}
        max-size=${MAX_UPLOAD_SIZE}
        placeholder="Drag &amp; drop your source archive, or"
        error=${this.#form.fieldError('source')}
        ?disabled=${this.#form.saving}
        @change=${(e: Event) => {
          [this.source] = (e.target as HTMLInputElement).files ?? [];
        }}
      ></moz-input-file>
      ${
        v.source
          ? html`
          <div class="delete-source">
              <span>or </span>
              <a
                class="link-button"
                ?disabled=${this.#form.saving}
                @click=${() => {
                  this.source = null;
                }}
                >Delete current source</a
              >
          </div>
          `
          : nothing
      }
    `;
  }

  #detailsHead(v: Version) {
    const form = this.#form;
    return this.cardHead(
      { title: 'Version details' },
      html`<div class="card-actions">
        ${form.editing ? nothing : this.#menu(v)}
        ${this.draftActions(
          form,
          () => this.#startEdit(v),
          () => this.#save(v),
        )}
      </div>`,
    );
  }

  #details(v: Version) {
    const form = this.#form;
    const hasSource = v.channel !== 'enterprise' && this.addon.kind !== 'theme';
    const notes = localized(v.release_notes);
    return html`
      ${this.errorBar(
        form.editing ? form.error : this.confirmingDelete ? '' : this.error,
      )}
      <dl>
        ${this.row(
          'Compatibility',
          html`
            ${this.#compat(v)}`,
        )}
        ${
          this.addon.kind !== 'theme'
            ? form.editing
              ? html`${textArea(form, 'release_notes', 'Release notes')}
              ${textArea(form, 'approval_notes', 'Notes for reviewers')}`
              : html`${this.row(
                  'Release notes',
                  notes ? html`<span>${notes}</span>` : null,
                )}
              ${this.row(
                'Notes for reviewers',
                v.approval_notes
                  ? html`<span>${v.approval_notes}</span>`
                  : null,
              )}`
            : nothing
        }
        ${
          form.editing
            ? this.#license(v)
            : this.row('License', this.#license(v))
        }
        ${this.row(
          'Approval status',
          html`<version-badge
            status=${v.file.status}
            ?user-disabled=${v.is_disabled}
            .reviewed=${v.reviewed}
          ></version-badge>`,
        )}
        ${hasSource ? this.row('Source code', this.#source(v)) : nothing}
      </dl>
    `;
  }

  #renderActivity = (item: Update) =>
    html`<chat-card .item=${item}></chat-card>`;

  #activityList() {
    const { data, isPending, isError, hasNextPage, isFetchingNextPage } =
      this.#activity();
    if (isError)
      return html`<p class="muted">Couldn't load activity. Try again.</p>`;
    if (isPending || !data) return html`<p class="muted">Loading activity…</p>`;
    const items = data.pages.flatMap((p) => p.items);
    if (!items.length) return html`<p class="muted">No activity yet.</p>`;
    return html`<app-infinite-list
      inverted
      class="activities"
      exportparts="foot, view"
      .items=${items}
      .renderItem=${this.#renderActivity}
      ?has-more=${hasNextPage}
      ?loading=${isFetchingNextPage}
      loading-label="Loading older activity…"
      @load-more=${() => this.#activity.fetchNextPage()}
    ></app-infinite-list>`;
  }

  #activityTab(v: Version) {
    const reply = this.#reply;
    return html`
      ${this.#activityList()}
      ${this.errorBar(reply.error)}
      <form
        class="reply"
        @submit=${(e: SubmitEvent) => {
          e.preventDefault();
          this.#sendReply(v);
        }}
      >
        ${textField(reply, 'comments', '', undefined, 'Reply')}
        <moz-button
          type="submit"
          variant="primary"
          icon-start="forward"
          icon-only="Send reply"
          ?disabled=${reply.saving || !reply.value('comments')?.trim()}
        ></moz-button>
      </form>
    `;
  }

  render() {
    const result = this.#version();
    if (result.isPending) return html`<p class="muted">Loading…</p>`;
    const v = result.data;
    if (!v) {
      return html`<error-page .code=${errorStatus(result.error)}></error-page>`;
    }
    return html`
      <addon-manage-header .addon=${this.addon} .version=${v}></addon-manage-header>
      <div class="main-content">
        ${this.#submissionLog()}
        <moz-card class="version-content" appearance="outline" spacing="spacious">
          <div class="version-head">
            <moz-segmented-control
              value=${this.tab}
              label="Version sections"
              fill
              size="small"
              @moz-segmented-control:change=${(
                e: CustomEvent<{ value: Tab }>,
              ) => {
                this.tab = e.detail.value;
              }}
            >
              <moz-segmented-control-item
                value="details"
                label="Version details"
              ></moz-segmented-control-item>
              <moz-segmented-control-item
                value="activity"
                label="Version activity and notifications"
              ></moz-segmented-control-item>
            </moz-segmented-control>
            ${this.tab === 'details' ? this.#detailsHead(v) : nothing}
          </div>
          ${this.tab === 'details' ? this.#details(v) : this.#activityTab(v)}
        </moz-card>
      </div>
      ${this.#deleteDialog(v)}
    `;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'version-detail': VersionDetail;
  }
}
