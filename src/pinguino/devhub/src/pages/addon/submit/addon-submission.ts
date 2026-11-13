import { Routes } from '@lit-labs/router';
import { html, nothing, type TemplateResult } from 'lit';
import { customElement, state } from 'lit/decorators.js';
import { BASE } from '../../../base';
import {
  addonFromUpload,
  addonQuery,
  getAddon,
  getLatestVersion,
  themePreviewQuery,
} from '../../../data/queries';
import type {
  Addon,
  AddonDistribution,
  AddonKind,
  Version,
} from '../../../data/types';
import { navigateTo } from '../../../utils/helper';
import { type StepId, SubmissionFlow } from './submission-flow';

import '../../../components/addon-listing/graphic-assets-card';
import '../../../components/addon-listing/listing-details-card';
import '../../../components/theme-preview';

const CHANNEL = '(listed|unlisted|enterprise)';

const THEME_CHANNEL = '(listed|unlisted)';
const SOURCE_CHANNEL = '(listed|unlisted)';

const BEFORE_CREATE = new Set<StepId>(['distribution', 'upload', 'validation']);

@customElement('addon-submission')
export class AddonSubmission extends SubmissionFlow {
  @state() protected kind: AddonKind = 'extension';

  #addon = addonQuery(this, () => this.addonSlug);

  #preview = themePreviewQuery(
    this,
    () => this.addonSlug,
    () =>
      this.isTheme &&
      this.channel === 'listed' &&
      this.steps[this.currStep]?.id === 'review' &&
      !this.#addon().data?.previewUrl,
  );

  protected get heading() {
    return this.isTheme ? 'Submit theme' : 'Submit extension';
  }

  protected get labels() {
    const noun = this.isTheme ? 'theme' : 'extension';
    return {
      distribution: this.isTheme
        ? 'Theme distribution'
        : 'Extension distribution',
      upload: `Upload ${noun}`,
    };
  }

  protected get isNewAddon() {
    return true;
  }

  protected _routes: Routes = new Routes(
    this,
    [
      {
        path: '',
        enter: () =>
          this.redirect(
            this.addonSlug
              ? this.url('finish', true)
              : this.url('distribution'),
          ),
      },
      {
        path: 'theme/',
        enter: () => this.enter('distribution', 'theme'),
      },
      {
        path: 'distribution',
        enter: () => this.enter('distribution', 'extension'),
        render: () => this.distributionStep(),
      },
      {
        path: 'theme/distribution',
        enter: () => this.enter('distribution', 'theme'),
        render: () => this.distributionStep(),
      },
      {
        path: `upload-:channel${CHANNEL}`,
        enter: ({ channel }) =>
          this.enterUpload(channel as AddonDistribution, 'extension'),
        render: () => this.uploadStep(),
      },
      {
        path: `theme/upload-:channel${THEME_CHANNEL}`,
        enter: ({ channel }) =>
          this.enterUpload(channel as AddonDistribution, 'theme'),
        render: () => this.uploadStep(),
      },
      {
        path: `source-:channel${SOURCE_CHANNEL}`,
        enter: ({ channel }) => this.enterSource(channel as AddonDistribution),
        render: () => this.whenHasVersion(() => this.sourceStep()),
      },
      {
        path: 'details',
        enter: () => this.enter('details', 'extension'),
        render: () => this.whenHasVersion(() => this.listingStep()),
      },
      {
        path: 'theme/details',
        enter: () => this.enter('details', 'theme'),
        render: () => this.whenHasVersion(() => this.listingStep()),
      },
      {
        path: 'graphics',
        enter: () => this.enter('graphics'),
        render: () => this.imagesStep(),
      },
      {
        path: 'review',
        enter: () => this.enter('review'),
        render: () =>
          this.whenHasVersion(() => this.reviewStep(this.reviewContent())),
      },
      {
        path: 'finish',
        enter: () => this.enter('finish'),
        render: () => this.finishStep(),
      },
    ],
    {
      fallback: {
        enter: () => this.goto(''),
      },
    },
  );

  protected async createFromUpload(uuid: string) {
    const { addon, version } = await addonFromUpload({
      version: { upload: uuid },
    });
    this.onCreate(version, addon);
  }

  protected onCreate(version: Version, addon?: Addon) {
    super.onCreate(version);
    if (!addon) return;
    this.latestSlug = addon.slug;
    this.kind = addon.kind;
  }

  private url(step: string, created = false) {
    if (!created) {
      return `${BASE}/addon/submit/${this.isTheme ? 'theme/' : ''}${step}`;
    }
    const slug = encodeURIComponent(decodeURIComponent(this.addonSlug));
    return slug ? `${BASE}/addon/${slug}/submit/${step}` : undefined;
  }

  // Without a step to go to, starts over (the start route picks where).
  private redirect(href?: string) {
    return href ? navigateTo(href, { replace: true }) : this.goto('');
  }

  private async enter(id: StepId, kind?: AddonKind) {
    if (kind) this.enterKind(kind);
    await this.lookUp();
    const created = Boolean(this.addonSlug);
    const index = this.indexOf(id);
    const href = this.steps[index]?.href;
    if (created && BEFORE_CREATE.has(id)) {
      return this.redirect(this.steps[this.indexOf('validation') + 1].href);
    }
    if (!href) return this.goto('');
    if (!created && !this.upload && index > this.indexOf('validation')) {
      return this.redirect(this.url(`upload-${this.channel}`));
    }
    if (href !== location.pathname) return this.redirect(href);
    return this.enterStep(id);
  }

  private enterKind(kind: AddonKind) {
    if (this.addonSlug || kind === this.kind) return;
    this.kind = kind;
    if (this.isTheme && this.channel === 'enterprise') this.channel = 'listed';
    this.resetUpload();
  }

  // A created add-on's steps depend on what it is and its version's channel,
  // which a deep link (e.g. a reload) looks up before entering one.
  private async lookUp() {
    const slug = this.addonSlug;
    if (!slug || this.versionId) return;
    try {
      const [addon, version] = await Promise.all([
        getAddon(slug),
        getLatestVersion(slug),
      ]);
      if (addon) this.kind = addon.kind;
      if (version) {
        this.versionId = version.id;
        this.channel = version.channel;
      }
    } catch {
      // Without them, the steps that need the version wait for it.
    }
  }

  private enterUpload(channel: AddonDistribution, kind: AddonKind) {
    this.enterKind(kind);
    if (!this.addonSlug && channel !== this.channel) {
      this.channel = channel;
      this.resetUpload();
    }
    return this.enter(this.upload ? 'validation' : 'upload');
  }

  private enterSource(channel: AddonDistribution) {
    if (!this.upload && !this.versionId) this.channel = channel;
    return this.enter('source', 'extension');
  }

  private reviewContent() {
    const addon = this.#addon().data;
    if (!addon) return nothing;
    const preview = this.isTheme ? this.themePreview(addon) : nothing;
    if (this.channel !== 'listed') return preview;
    return html`${preview}
      <listing-details-card
        .addon=${addon}
        .versionId=${this.versionId}
      ></listing-details-card>
      ${
        this.isTheme
          ? nothing
          : html`<graphic-assets-card .addon=${addon}></graphic-assets-card>`
      }`;
  }

  private themePreview(addon: Addon) {
    const rendered = addon.previewUrl ? addon : this.#preview().data;
    if (rendered?.previewUrl) {
      return html`<theme-preview
        slot="preview"
        .addon=${rendered}
      ></theme-preview>`;
    }
    return this.channel === 'listed'
      ? html`<message-bar
          slot="preview"
          heading="Generating theme preview…"
        ></message-bar>`
      : nothing;
  }

  private whenHasVersion(render: () => TemplateResult) {
    return this.addonSlug && !this.versionId ? nothing : render();
  }

  protected stepHrefs() {
    const { channel } = this;
    const upload = this.url(`upload-${channel}`);
    return {
      distribution: this.url('distribution'),
      upload,
      validation: upload,
      source:
        this.url(`source-${channel}`, true) ??
        (channel === 'listed' ? this.url('source-listed') : undefined),
      details: this.url('details', true) ?? this.url('details'),
      graphics: this.url('graphics', true),
      review: this.url('review', true),
      finish: this.url('finish', true),
    };
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'addon-submission': AddonSubmission;
  }
}
