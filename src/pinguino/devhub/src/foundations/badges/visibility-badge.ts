import type { IconName, MozPanelList } from 'acorn-web-components';
import { css, html, LitElement, nothing } from 'lit';
import { customElement, property, query } from 'lit/decorators.js';
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
    .chevron {
      --icon-size: var(--icon-size-xsmall);
    }
    moz-panel-list {
      padding: var(--space-xlarge);
      max-inline-size: 24rem;
    }
  `;

  @query('moz-panel-list') private panel!: MozPanelList;

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
          ? html`<moz-button
              variant='ghost'
              size="small"
              @click=${(e: Event) => this.panel.toggle(e, e.currentTarget as HTMLElement)}
            >
              ${badge}
            </moz-button>`
          : badge
      }
      <moz-panel-list type="slot" align="start">
        <slot @slotchange=${() => this.requestUpdate()}></slot>
      </moz-panel-list>
    `;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'visibility-badge': VisibilityBadge;
  }
}
