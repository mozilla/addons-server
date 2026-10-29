import { css, html, LitElement } from 'lit';
import { customElement, property } from 'lit/decorators.js';
import type { StatusInfo } from '../../data';

export type ListingStatusType = StatusInfo['badge'];

/**
 * The pill the manage header uses for an add-on's state. Not `moz-status-badge`:
 * that one is 22px and colours its approved state green, where this is the
 * design's 32px pill whose approved state is an outline with a green dot
 * (Figma: "Status with menu size L", node 1353-38820).
 *
 * Purely presentational. One `type` drives both the surface and the dot, so a
 * caller can't pair a green dot with a rejected pill: approved is a green dot
 * on an outline, pending/incomplete a yellow dot on yellow, rejected and
 * Mozilla-disabled a red dot on red, and developer-hidden a muted dot on an
 * offset surface.
 */
@customElement('listing-status-badge')
export class ListingStatusBadge extends LitElement {
  @property({ reflect: true }) type: ListingStatusType = 'default';

  static styles = css`
    :host {
      display: inline-flex;
      vertical-align: middle;
      --listing-status-background: var(--background-color-canvas);
      --listing-status-border: transparent;
    }
    .badge {
      box-sizing: border-box;
      display: inline-flex;
      align-items: center;
      gap: var(--space-small);
      min-block-size: 32px;
      padding-inline: var(--space-large);
      border: var(--border-width) solid var(--listing-status-border);
      border-radius: var(--border-radius-xlarge);
      background-color: var(--listing-status-background);
      color: var(--text-color);
      font-size: var(--font-size-root);
    }
    /* moz-status-dot is a 22px circle, which at this size reads as a ball
       rather than the design's small dot. */
    moz-status-dot::part(dot) {
      block-size: 8px;
      inline-size: 8px;
    }
    :host([type='success']) {
      --listing-status-background: var(--background-color-box);
      --listing-status-border: var(--border-color-selected);
    }
    :host([type='warning']) {
      --listing-status-background: var(--background-color-warning);
    }
    :host([type='critical']) {
      --listing-status-background: var(--background-color-critical);
    }
    /* Hidden by the developer: an offset surface rather than no surface, so it
       still reads as a state. moz-status-dot has no colour for this one, so
       give it a muted dot instead of the information blue it defaults to. */
    :host([type='ghost']) {
      --listing-status-background: var(--background-color-canvas);
      --listing-status-border: var(--border-color-deemphasized);
    }
    :host([type='ghost']) moz-status-dot {
      --status-dot-color: var(--text-color-deemphasized);
    }
    @media (forced-colors: active) {
      .badge {
        border-color: canvastext;
      }
    }
  `;

  render() {
    return html`
      <span class="badge" part="badge">
        <moz-status-dot type=${this.type}></moz-status-dot>
        <span class="label"><slot></slot></span>
      </span>
    `;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'listing-status-badge': ListingStatusBadge;
  }
}
