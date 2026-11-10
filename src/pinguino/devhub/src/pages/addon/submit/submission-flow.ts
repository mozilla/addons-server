import type { Routes } from '@lit-labs/router';
import { css, html, LitElement, nothing } from 'lit';
import { property, query, state } from 'lit/decorators.js';
import { BASE } from '../../../base';
import {
  addonQuery,
  disableVersion,
  profileQuery,
} from '../../../data/queries';
import type {
  Addon,
  AddonDistribution,
  AddonKind,
  FileUpload,
  Version,
} from '../../../data/types';
import type {
  TimelineSection,
  TimelineStep,
} from '../../../foundations/components/timeline-nav';
import { navigateTo } from '../../../utils/helper';
import { errorMessage, type SubmissionStep } from './submission-step';
import '../../../foundations/components/message-bar';
import '../../../foundations/components/timeline-nav';
import './templates/distribution';
import './templates/finish';
import './templates/images';
import './templates/listing';
import './templates/review';
import './templates/source';
import './templates/upload';

export type StepId =
  | 'distribution'
  | 'upload'
  | 'validation'
  | 'source'
  | 'details'
  | 'graphics'
  | 'review'
  | 'finish';
export type FlowStep = TimelineStep & { id: StepId };
export type FlowSection = TimelineSection & { steps: FlowStep[] };

// The labels the flows word differently.
export type FlowLabels = {
  distribution: string;
  // The upload's section, and its step.
  upload: string;
};

export abstract class SubmissionFlow extends LitElement {
  @property() slug = '';

  @state() protected versionId?: number;
  @state() protected currStep = 0;
  @state() private submitting = false;

  @state() private stepReady = false;
  @state() private cancelError?: string;
  @query('#cancel-dialog') private cancelDialog?: HTMLElement & {
    open: boolean;
  };

  @state() protected channel: AddonDistribution = 'listed';
  @state() protected upload?: FileUpload;

  @query('.outlet > *') private stepElement?: SubmissionStep;
  #sections?: { key: string; sections: FlowSection[] };
  #uploadElement = this.#createUploadElement();

  // The submit notice comes from the profile's site status, falling back to the
  // add-on's per-channel submission warning.
  #profile = profileQuery(this);
  #addon = addonQuery(this, () => this.slug);

  static styles = css`
    .main-content {
      display: flex;
      gap: var(--space-medium);
    }
    .step-content {
      flex-basis: 75%;
    }
    .step-count {
      color: var(--text-color-deemphasized);
    }
    timeline-nav {
      flex-basis: 25%;
      min-width: 250px;
    }
    moz-page-header {
      padding: var(--space-large) 0;
    }
    .step-content > * {
      padding: var(--space-medium);
    }
    .step-content moz-message-bar {
      padding: 0;
    }
    .continue {
      display: flex;
      justify-content: space-between;
      align-items: center;
    }
    #cancel-dialog p {
      margin: 0;
    }
  `;

  protected abstract readonly heading: string;
  protected abstract readonly kind: AddonKind;
  protected abstract readonly labels: FlowLabels;
  protected abstract readonly _routes: Routes;
  protected abstract stepHrefs(): Record<StepId, string | undefined>;
  protected abstract createFromUpload(uuid: string): Promise<void>;

  // The add-on's slug as created or renamed here. The URL's lags behind it
  // until the router catches up, and a new add-on's is empty again after
  // browser back to a page from before it existed.
  @state() protected latestSlug?: string;
  @state() protected pendingSource?: File;

  protected get addonSlug() {
    return this.latestSlug || this.slug;
  }

  protected get isTheme() {
    return this.kind === 'theme';
  }

  protected get isNewAddon() {
    return false;
  }

  protected get hasSource() {
    return this.channel !== 'enterprise' && !this.isTheme;
  }

  protected get showListingDetails() {
    return this.channel === 'listed';
  }

  protected get canSubmitListed() {
    return true;
  }

  protected goto(path: string) {
    return navigateTo(path, { routes: this._routes, replace: true });
  }

  protected onCreate(version: Version, _addon?: Addon) {
    this.versionId = version.id;
    this.pendingSource = undefined;
  }

  protected distributionStep() {
    return html`<submit-distribution
      ?theme=${this.isTheme}
      ?no-listed=${!this.canSubmitListed}
      .channel=${this.channel}
      @distribution-change=${(e: CustomEvent<{ value: AddonDistribution }>) => {
        this.channel = e.detail.value;
        this.resetUpload();
      }}
    ></submit-distribution>`;
  }

  #createUploadElement() {
    const el = document.createElement('submit-upload');
    el.addEventListener('upload-change', (e) => {
      this.setUpload(e.detail.upload);
    });
    el.create = async (uuid) => {
      if (!this.showListingDetails) await this.createFromUpload(uuid);
    };
    return el;
  }

  protected uploadStep() {
    const el = this.#uploadElement;
    el.channel = this.channel;
    el.uuid = this.upload?.uuid;
    return el;
  }

  protected sourceStep() {
    return html`<submit-source
      .slug=${this.addonSlug}
      .versionId=${this.versionId}
      @source-select=${(e: CustomEvent<{ file?: File }>) => {
        this.pendingSource = e.detail.file;
      }}
    ></submit-source>`;
  }

  protected listingStep() {
    return html`<submit-listing
      .slug=${this.addonSlug}
      .versionId=${this.versionId}
      .upload=${this.upload?.uuid}
      .source=${this.pendingSource}
      .kind=${this.kind}
      @addon-create=${(e: CustomEvent<{ addon: Addon; version: Version }>) =>
        this.onCreate(e.detail.version, e.detail.addon)}
      @version-create=${(e: CustomEvent<{ version: Version }>) =>
        this.onCreate(e.detail.version)}
      @addon-slug-change=${(e: CustomEvent<{ slug: string }>) => {
        this.latestSlug = e.detail.slug;
      }}
    ></submit-listing>`;
  }

  protected imagesStep() {
    return html`<submit-images .slug=${this.addonSlug}></submit-images>`;
  }

  protected reviewStep(content: unknown = nothing) {
    return html`<review-submit
      ?theme=${this.isTheme}
      ?new-addon=${this.isNewAddon}
      .slug=${this.addonSlug}
      .versionId=${this.versionId}
      .distribution=${this.channel}
      >${content}</review-submit
    >`;
  }

  protected finishStep() {
    return html`<submit-finish ?theme=${this.isTheme}></submit-finish>`;
  }

  protected buildSections(): FlowSection[] {
    const href = this.stepHrefs();
    const { labels } = this;
    const step = (id: StepId, label: string): FlowStep => ({
      id,
      label,
      href: href[id],
    });
    return [
      {
        title: labels.upload,
        steps: [
          step('distribution', labels.distribution),
          step('upload', labels.upload),
          step('validation', 'Validation'),
          ...(this.hasSource ? [step('source', 'Upload source code')] : []),
        ],
      },
      ...(this.showListingDetails
        ? [
            {
              title: 'Create your listing',
              steps: [
                step('details', 'Listing details'),
                ...(this.isTheme ? [] : [step('graphics', 'Add images')]),
              ],
            },
          ]
        : []),
      {
        title: 'Review',
        steps: [
          { ...step('review', 'Review before submitting'), canSubmit: true },
          step('finish', 'Submit'),
        ],
      },
    ];
  }

  private setUpload(upload: FileUpload | undefined) {
    if (upload) this.upload = upload;
    else this.clearUpload();
    const current = this.steps[this.currStep]?.id;
    if (current === 'upload' || current === 'validation') {
      this.currStep = this.indexOf(upload ? 'validation' : 'upload');
    }
  }

  // Changing the package invalidates other steps.
  protected clearUpload() {
    this.upload = undefined;
    this.versionId = undefined;
    this.pendingSource = undefined;
  }

  protected resetUpload() {
    this.clearUpload();
    this.#uploadElement.reset();
  }

  // Keep currStep in sync with the URL so browser back/forward and reloads
  // land on the right step. Steps sharing a route (upload/validation) keep
  // whichever one is current.
  protected enterStep(id: StepId) {
    const { steps } = this;
    const target = this.indexOf(id);
    if (steps[this.currStep]?.href !== steps[target].href) {
      this.currStep = target;
    }
    return true;
  }

  protected get sections(): FlowSection[] {
    const key = `${this.addonSlug}/${this.versionId}/${this.channel}/${this.isTheme}/${this.showListingDetails}`;
    if (this.#sections?.key !== key) {
      this.#sections = { key, sections: this.buildSections() };
    }
    return this.#sections.sections;
  }

  protected get steps(): FlowStep[] {
    return this.sections.flatMap((section) => section.steps);
  }

  protected indexOf(id: StepId) {
    return this.steps.findIndex((step) => step.id === id);
  }

  private navigate(target: number) {
    this.stepReady = false;
    const { href } = this.steps[target];
    if (href) navigateTo(href);
    this.currStep = target;
  }

  private async submitStep(): Promise<boolean> {
    if (!this.stepElement) return true;
    this.submitting = true;
    try {
      return await this.stepElement.submit();
    } finally {
      this.submitting = false;
    }
  }

  private async moveTo(target: number) {
    const { steps } = this;
    if (steps[target].href === steps[this.currStep].href) {
      this.currStep = target;
      return;
    }
    if (!(await this.submitStep())) return;
    this.navigate(target);
  }

  private nextStep() {
    const { steps } = this;
    let next = Math.min(this.currStep + 1, steps.length - 1);
    if (steps[next].id === 'upload' && this.upload) next += 1;
    return this.moveTo(next);
  }

  private prevStep() {
    let prev = Math.max(this.currStep - 1, 0);
    if (this.steps[prev].id === 'upload' && this.upload) prev -= 1;
    this.navigate(prev);
  }

  private async cancelVersion() {
    if (!this.versionId) return;
    this.submitting = true;
    try {
      await disableVersion(this.addonSlug, this.versionId);
      navigateTo(`${BASE}/addon/${encodeURIComponent(this.addonSlug)}`);
    } catch (err) {
      this.cancelError = errorMessage(err);
    } finally {
      this.submitting = false;
    }
  }

  private renderCancelDialog() {
    return html`
      <moz-dialog id="cancel-dialog" heading="Cancel and Disable Version">
        <p>Are you sure you wish to cancel and disable version?</p>
        ${
          this.cancelError
            ? html`<moz-message-bar type="error"
                >${this.cancelError}</moz-message-bar
              >`
            : nothing
        }
        <moz-button slot="actions" variant="ghost" data-dismiss>
          No, don't cancel
        </moz-button>
        <moz-button
          slot="actions"
          variant="destructive"
          ?disabled=${this.submitting}
          @click=${this.cancelVersion}
        >
          Yes, Cancel
        </moz-button>
      </moz-dialog>
    `;
  }

  private canSubmit() {
    return (
      Boolean(this.steps[this.currStep]?.canSubmit) &&
      this.stepReady &&
      !this.submitting
    );
  }

  private renderSecondaryAction() {
    if (this.versionId) {
      return html`<moz-button
        variant="destructive"
        size="medium"
        ?disabled=${this.submitting}
        @click=${() => {
          this.cancelError = undefined;
          if (this.cancelDialog) this.cancelDialog.open = true;
        }}
      >
        Cancel and Disable Version
      </moz-button>`;
    }
    if (this.currStep > 0) {
      return html`<moz-button
        variant="ghost"
        size="medium"
        ?disabled=${this.submitting}
        @click=${this.prevStep}
      >
        Back
      </moz-button>`;
    }
    return html`<moz-button variant="ghost" size="medium">Cancel</moz-button>`;
  }

  private renderContinue() {
    return html`
      <div class="continue">
        <p class="step-count">Step ${this.currStep + 1}/${this.steps.length}</p>
        <div>
          ${this.renderSecondaryAction()}
          <moz-button
            @click=${this.nextStep}
            ?disabled=${this.submitting || !this.stepReady}
            variant="default"
            size="medium"
          >
            Continue
          </moz-button>
        </div>
      </div>
    `;
  }

  private renderCrumbs() {
    return html`
      <moz-breadcrumb-group label="Breadcrumb">
        ${this.steps
          .slice(0, this.currStep + 1)
          .map(({ label }) => html`<moz-breadcrumb>${label}</moz-breadcrumb>`)}
      </moz-breadcrumb-group>
    `;
  }

  private renderSubmitNotice() {
    // The add-on's warning is per channel
    const addonNotice = this.#addon().data?.submissionNotice?.[this.channel];
    const message =
      this.#profile().data?.siteStatus?.submissionNotice ?? addonNotice;
    if (!message) return nothing;
    return html`
      <moz-message-bar id="submit-status-banner" type="warning" variant="default">
        ${message}
      </moz-message-bar>
    `;
  }

  render() {
    const finish = this.indexOf('finish');
    return html`
      <moz-page-header heading=${this.heading}>
        <moz-button
          slot="actions"
          variant="primary"
          ?disabled=${!this.canSubmit()}
          @click=${() => this.moveTo(finish)}
        >
          Submit
        </moz-button>
      </moz-page-header>
      <div class="main-content">
        <timeline-nav
          .sections=${this.sections}
          .currStep=${this.currStep}
          ?completed=${this.currStep === finish}
          @timeline-nav:change=${(e: CustomEvent<{ index: number }>) =>
            (this.currStep = e.detail.index)}
        ></timeline-nav>
        <moz-card class="step-content">
          ${this.renderCrumbs()}
          ${this.renderSubmitNotice()}
          <div
            class="outlet"
            @step-ready=${(e: CustomEvent<{ ready: boolean }>) => {
              this.stepReady = e.detail.ready;
            }}
          >
            ${this._routes.outlet()}
          </div>
          ${
            this.currStep < this.indexOf('review')
              ? this.renderContinue()
              : nothing
          }
        </moz-card>
      </div>
      ${this.renderCancelDialog()}
    `;
  }
}
