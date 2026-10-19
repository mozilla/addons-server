import { html } from 'lit';
import { customElement, property } from 'lit/decorators.js';
import { DISTRIBUTION } from '../../../../components/addon-card';
import type { AddonDistribution } from '../../../../data/types';
import { emit, SubmissionStep } from '../submission-flow';

const OPTIONS: Record<
  AddonDistribution,
  { label: string; description: string }
> = {
  listed: {
    label: 'On AMO (addons.mozilla.org)',
    description:
      'Listed on addons.mozilla.org and in Firefox Add-ons Manager after code review. Automatic updates are handled by this site. Eligible for Mozilla promotions; self-distribution of reviewed files is also possible.',
  },
  unlisted: {
    label: 'On your own',
    description:
      'Immediately signed for self-distribution. You handle updates via updateURL or your own application.',
  },
  enterprise: {
    label: 'Enterprise',
    description:
      'After your submission is signed by Mozilla, you can download the .xpi file from the Developer Hub and distribute it to your audience via a Firefox for Enterprise policy.',
  },
};

@customElement('submit-distribution')
export class SubmitDistribution extends SubmissionStep {
  @property() channel?: AddonDistribution;

  protected get ready() {
    return !!this.channel;
  }

  private onChange(e: Event) {
    const { value } = e.target as HTMLInputElement;
    emit(this, 'distribution-change', { value });
  }

  render() {
    return html`
      <submission-header
        label="Add-on distribution"
        description="Choose how this version will be distributed before you upload."
      ></submission-header>
      <moz-visual-picker
        orientation="vertical"
        variant="radio"
        .value=${this.channel}
        @change=${this.onChange}
      >
        ${(Object.keys(OPTIONS) as AddonDistribution[]).map((value) => {
          const { label, description } = OPTIONS[value];
          const badge = DISTRIBUTION[value];
          return html`<moz-visual-picker-item
              value=${value}
              label=${label}
              description=${description}
            >
              <moz-status-badge slot="badge" icon-start=${badge.icon}
                >${badge.label}</moz-status-badge
              >
            </moz-visual-picker-item>`;
        })}
      </moz-visual-picker>
    `;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'submit-distribution': SubmitDistribution;
  }
}
