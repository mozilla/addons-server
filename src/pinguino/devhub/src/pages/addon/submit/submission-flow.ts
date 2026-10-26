import { Routes } from '@lit-labs/router';
import {
  type CSSResultGroup,
  css,
  html,
  LitElement,
  nothing,
  type PropertyValues,
} from 'lit';
import { customElement, property, query, state } from 'lit/decorators.js';
import { BASE } from '../../../base';
import { disableVersion } from '../../../data/queries';
import type { AddonDistribution, FileUpload } from '../../../data/types';
import type {
  TimelineSection,
  TimelineStep,
} from '../../../foundations/components/timeline-nav';
import { navigateTo } from '../../../helper';
import '../../../foundations/components/message-bar';
import '../../../foundations/components/timeline-nav';

export function emit(el: HTMLElement, type: string, detail: unknown) {
  el.dispatchEvent(
    new CustomEvent(type, { detail, bubbles: true, composed: true }),
  );
}

export function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

export function errorBar(heading: string, message?: string) {
  return message
    ? html`<message-bar
        type="error"
        heading=${heading}
        description=${message}
      ></message-bar>`
    : nothing;
}

type FlowStep = TimelineStep & { id: string };
type FlowSection = TimelineSection & { steps: FlowStep[] };

export abstract class SubmissionStep extends LitElement {
  // Typed wider than the inferred CSSResult so subclasses can compose it into
  // an array, which is how they all extend these styles.
  static styles: CSSResultGroup = css`
    :host {
      display: flex;
      flex-direction: column;
      gap: var(--space-large);
    }
  `;

  protected abstract get ready(): boolean;

  connectedCallback() {
    super.connectedCallback();
    if (this.hasUpdated) this.requestUpdate();
  }

  updated(changed: PropertyValues) {
    super.updated(changed);
    emit(this, 'step-ready', { ready: this.ready });
  }

  async submit(): Promise<boolean> {
    return true;
  }
}

@customElement('submission-header')
export class SubmissionHeader extends LitElement {
  static styles = css`
    :host {
      display: flex;
      flex-direction: column;
      gap: 0.25em;
    }
    legend {
      padding: 0;
      font-weight: var(--font-weight-heading);
    }
    .description {
      margin: 0;
      color: var(--text-color-deemphasized);
      font-size: var(--font-size-small);
    }
  `;

  @property() label?: string;
  @property() description?: string;

  render() {
    return html`
      ${this.label && html`<legend>${this.label}</legend>`}
      ${this.description && html`<p class="description">${this.description}</p>`}
    `;
  }
}

@customElement('addon-submission')
export class AddonSubmission extends LitElement {
  @property() slug = '';

  @state() private versionId?: number;
  @state() private currStep = 0;
  @state() private submitting = false;

  @state() private stepReady = false;
  @state() private cancelError?: string;
  @query('#cancel-dialog') private cancelDialog?: HTMLElement & {
    open: boolean;
  };

  // TODO: Default to last used channel.
  @state() private channel: AddonDistribution = 'listed';
  @state() private upload?: FileUpload;
  @state() private canCreateVersion = false;

  @query('.outlet > *') private stepElement?: SubmissionStep;
  #sections?: { versionId?: number; sections: FlowSection[] };
  #uploadElement?: HTMLElementTagNameMap['submit-upload'];

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
    .continue {
      display: flex;
      justify-content: space-between;
      align-items: center;
    }
    #cancel-dialog p {
      margin: 0;
    }
  `;

  private _routes: Routes = new Routes(
    this,
    [
      {
        path: '',
        enter: () => this.enterStep(this.upload ? 'validation' : 'upload'),
        render: () => this.uploadStep(),
      },
      {
        path: 'distribution',
        enter: () => this.enterStep('distribution'),
        render: () =>
          html`<submit-distribution
            .channel=${this.channel}
            @distribution-change=${(
              e: CustomEvent<{ value: AddonDistribution }>,
            ) => {
              this.channel = e.detail.value;
              this.resetUpload();
            }}
          ></submit-distribution>`,
      },
      {
        path: ':versionId/source',
        enter: (params) => this.enterVersion(params, 'source'),
        render: ({ versionId }) =>
          html`<submit-source
            .slug=${this.slug}
            .versionId=${Number(versionId)}
          ></submit-source>`,
      },
      {
        path: ':versionId/details',
        enter: (params) => this.enterVersion(params, 'review'),
        render: ({ versionId }) =>
          html`<review-submit
            .slug=${this.slug}
            .versionId=${Number(versionId)}
            .distribution=${this.channel}
          ></review-submit>`,
      },
      {
        path: ':versionId/finish',
        enter: (params) => this.enterVersion(params, 'finish'),
        render: () => html`<submit-finish></submit-finish>`,
      },
    ],
    {
      fallback: {
        enter: () => navigateTo('', { routes: this._routes, replace: true }),
      },
    },
  );

  private uploadStep() {
    if (!this.#uploadElement) {
      const el = document.createElement('submit-upload');
      el.addEventListener('version-create', (e) => {
        this.versionId = e.detail.id;
      });
      el.addEventListener('upload-change', (e) => {
        this.setUpload(e.detail.upload);
      });
      this.#uploadElement = el;
    }
    const el = this.#uploadElement;
    el.slug = this.slug;
    el.channel = this.channel;
    el.uuid = this.upload?.uuid;
    return el;
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
  private clearUpload() {
    this.upload = undefined;
    this.versionId = undefined;
    this.canCreateVersion = false;
  }

  private resetUpload() {
    this.clearUpload();
    this.#uploadElement?.reset();
  }

  // Keep currStep in sync with the URL so browser back/forward and reloads
  // land on the right step. Steps sharing a route (upload/validation) keep
  // whichever one is current.
  private enterStep(id: string) {
    const { steps } = this;
    const target = this.indexOf(id);
    if (steps[this.currStep]?.href !== steps[target].href) {
      this.currStep = target;
    }
    return true;
  }

  private enterVersion({ versionId }: { versionId?: string }, id: string) {
    this.versionId = Number(versionId);
    return this.enterStep(id);
  }

  private get sections(): FlowSection[] {
    const { versionId } = this;
    if (this.#sections?.versionId !== versionId || !this.#sections) {
      this.#sections = { versionId, sections: this.buildSections() };
    }
    return this.#sections.sections;
  }

  private buildSections(): FlowSection[] {
    const link = (step: string) => this._routes.link(step);
    const versionLink = (step: string) =>
      this.versionId ? link(`${this.versionId}/${step}`) : undefined;
    return [
      {
        title: 'Upload Version',
        steps: [
          {
            id: 'distribution',
            label: 'Add-on distribution',
            href: link('distribution'),
          },
          { id: 'upload', label: 'Upload version', href: link('') },
          { id: 'validation', label: 'Validation', href: link('') },
          {
            id: 'source',
            label: 'Upload source code',
            href: versionLink('source'),
          },
        ],
      },
      {
        title: 'Review',
        steps: [
          {
            id: 'review',
            label: 'Review before submit',
            href: versionLink('details'),
          },
          { id: 'finish', label: 'Submit', href: versionLink('finish') },
        ],
      },
    ];
  }

  private get steps(): FlowStep[] {
    return this.sections.flatMap((section) => section.steps);
  }

  private indexOf(id: string) {
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
    if (steps[this.currStep].id === 'source') this.canCreateVersion = true;
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
      await disableVersion(this.slug, this.versionId);
      navigateTo(`${BASE}/addon/${encodeURIComponent(this.slug)}`);
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
      Boolean(this.versionId && this.upload) &&
      this.canCreateVersion &&
      this.stepReady &&
      !this.submitting &&
      this.currStep < this.indexOf('finish')
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

  render() {
    const finish = this.indexOf('finish');
    return html`
      <moz-page-header heading="Submit a new version">
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
          <div
            class="outlet"
            @step-ready=${(e: CustomEvent<{ ready: boolean }>) => {
              this.stepReady = e.detail.ready;
              if (
                !e.detail.ready &&
                this.steps[this.currStep].id === 'source'
              ) {
                this.canCreateVersion = false;
              }
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

declare global {
  interface HTMLElementTagNameMap {
    'addon-submission': AddonSubmission;
    'submission-header': SubmissionHeader;
  }
}
