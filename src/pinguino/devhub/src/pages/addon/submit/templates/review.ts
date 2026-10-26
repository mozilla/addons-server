import { css, html, nothing } from 'lit';
import { customElement, property, query, state } from 'lit/decorators.js';
import { uploadVersionNotes, versionQuery } from '../../../../data/queries';
import type { AddonDistribution } from '../../../../data/types';
import { errorBar, errorMessage, SubmissionStep } from '../submission-flow';
import '../../../../components/not-found';
import '../../../../foundations/components/message-bar';
import { DISTRIBUTION } from '../../../../foundations/badges/distribution-badge';

type Textarea = HTMLElement & { value: string };

@customElement('review-submit')
export class ReviewSubmit extends SubmissionStep {
  static styles = [
    SubmissionStep.styles,
    css`
    dl {
      display: flex;
      flex-direction: column;
      gap: var(--space-large);
      margin: 0;
    }
    dt {
      margin-block-end: var(--space-xsmall);
      color: var(--text-color-deemphasized);
      font-size: var(--font-size-small);
    }
    dd {
      margin: 0;
    }
    .notes {
      display: flex;
      flex-direction: column;
      gap: var(--space-large);
    }
  `,
  ];

  @property() slug = '';
  @property({ type: Number }) versionId?: number;
  @property() distribution!: AddonDistribution;
  @state() private error?: string;

  @query('#release-notes') private releaseNotes?: Textarea;
  @query('#reviewer-notes') private reviewerNotes?: Textarea;

  #version = versionQuery(
    this,
    () => this.slug,
    () => this.versionId ?? 0,
  );

  protected get ready() {
    return Boolean(this.#version().data);
  }

  async submit(): Promise<boolean> {
    if (!this.versionId) return false;
    try {
      await uploadVersionNotes(
        this.slug,
        this.versionId,
        this.releaseNotes?.value.trim(),
        this.reviewerNotes?.value,
      );
      return true;
    } catch (err) {
      this.error = errorMessage(err);
      return false;
    }
  }

  render() {
    const query = this.#version();
    if (query.isPending) return nothing;
    if (query.isError) return html`<not-found></not-found>`;
    const version = query.data;
    const packageName = version.file.url.split('/').pop() ?? '';
    const distribution = DISTRIBUTION[this.distribution];
    return html`
      <submission-header
        label="Review before submit"
      ></submission-header>

      <dl>
        <div>
          <dt>Package</dt>
          <dd>${packageName}</dd>
        </div>
        <div>
          <dt>Version number</dt>
          <dd>${version.version}</dd>
        </div>
        <div>
          <dt>Distribution</dt>
          <dd>
            <moz-status-badge icon-start=${distribution.icon}
              >${distribution.label}</moz-status-badge
            >
          </dd>
        </div>
      </dl>

      <moz-card heading="Notes" appearance="outline">
        <div class="notes">
          <moz-textarea
            id="release-notes"
            label="Release notes"
            rows="2"
            full-width
          ></moz-textarea>
          <moz-textarea
            id="reviewer-notes"
            label="Notes for reviewer"
            rows="2"
            full-width
          ></moz-textarea>
        </div>
      </moz-card>

      ${errorBar('Could not save notes.', this.error)}
    `;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'review-submit': ReviewSubmit;
  }
}
