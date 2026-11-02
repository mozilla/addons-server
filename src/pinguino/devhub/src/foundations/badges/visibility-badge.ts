import type { IconName } from 'acorn-web-components';
import { css, html, LitElement, nothing } from 'lit';
import { customElement, property } from 'lit/decorators.js';
import { type AddonVisibility, VISIBILITY } from '../../data';

export const VISIBILITY_ICON: Record<AddonVisibility, IconName> = {
  visible: 'show-password',
  invisible: 'show-password-slash',
};

@customElement('visibility-badge')
export class VisibilityBadge extends LitElement {
  @property() visibility: AddonVisibility = 'visible';
  @property({ type: Boolean, reflect: true }) bordered = false;

  // Transparent host, so the badge itself is the flex item in the parent row.
  static styles = css`
    :host {
      display: contents;
    }
    .toggle {
      display: inline-flex;
      background: none;
      border: none;
      cursor: pointer;
    }
    moz-status-badge::part(badge) {
      padding-inline: var(--space-small);
      background-color: var(--color-white-alpha-70);
    }
    .chevron {
      --icon-size: var(--icon-size-xsmall);
    }
    .popover {
      position-area: bottom span-right;
      border: 1px solid var(--color-violet-desaturated-10);
      border-radius: var(--border-radius-xlarge);
      margin: var(--space-small) 0;
      padding: var(--space-xlarge);
      inline-size: 60%;
    }
  `;

  render() {
    const hasPopover = this.childElementCount > 0;
    const badge = html`
      <moz-status-badge type="ghost" icon-start=${VISIBILITY_ICON[this.visibility]}>
        ${VISIBILITY[this.visibility].label}
        ${
          hasPopover
            ? html`<moz-icon class="chevron" name="chevron-down-small"></moz-icon>`
            : nothing
        }
      </moz-status-badge>
    `;
    return html`
      ${
        hasPopover
          ? html`<button class="toggle" popovertarget="popover">${badge}</button>`
          : badge
      }
      <div id="popover" class="popover" popover>
        <slot @slotchange=${() => this.requestUpdate()}></slot>
      </div>
    `;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'visibility-badge': VisibilityBadge;
  }
}
