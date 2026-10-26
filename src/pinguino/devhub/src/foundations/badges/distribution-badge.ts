import type { IconName } from 'acorn-web-components';
import { css, html, LitElement } from 'lit';
import { customElement, property } from 'lit/decorators.js';
import type { AddonDistribution } from '../../data';

export const DISTRIBUTION: Record<
  AddonDistribution,
  { label: string; icon: IconName }
> = {
  listed: { label: 'AMO', icon: 'globe' },
  unlisted: { label: 'Self', icon: 'home' },
  enterprise: { label: 'Enterprise', icon: 'organizational-unit' },
};

@customElement('distribution-badge')
export class DistributionBadge extends LitElement {
  @property() distribution: AddonDistribution = 'listed';

  static styles = css`
    :host {
      display: contents;
    }
  `;

  render() {
    const { label, icon } = DISTRIBUTION[this.distribution];
    return html`
      <moz-status-badge type="ghost" icon-start=${icon}>
        ${label}
      </moz-status-badge>
    `;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'distribution-badge': DistributionBadge;
  }
}
