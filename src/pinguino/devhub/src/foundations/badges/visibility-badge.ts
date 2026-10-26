import type { IconName } from 'acorn-web-components';
import { css, html, LitElement } from 'lit';
import { customElement, property } from 'lit/decorators.js';
import { type AddonVisibility, VISIBILITY } from '../../data';

export const VISIBILITY_ICON: Record<AddonVisibility, IconName> = {
  visible: 'show-password',
  invisible: 'show-password-slash',
};

@customElement('visibility-badge')
export class VisibilityBadge extends LitElement {
  @property() visibility: AddonVisibility = 'visible';

  // Transparent host, so the badge itself is the flex item in the parent row.
  static styles = css`
    :host {
      display: contents;
    }
  `;

  render() {
    return html`
      <moz-status-badge type="ghost" icon-start=${VISIBILITY_ICON[this.visibility]}>
        ${VISIBILITY[this.visibility].label}
      </moz-status-badge>
    `;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'visibility-badge': VisibilityBadge;
  }
}
