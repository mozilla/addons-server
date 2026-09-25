import { css, html, LitElement } from 'lit';
import { customElement, property } from 'lit/decorators.js';
import type { Update } from '../data';

@customElement('update-card')
export class UpdateCard extends LitElement {
  // Not `update`: that's a LitElement lifecycle method.
  @property({ attribute: false }) item!: Update;

  static styles = css`
    :host {
      display: block;
    }
    .card {
      box-sizing: border-box;
      display: flex;
      flex-direction: column;
      gap: var(--space-small);
      padding: var(--space-medium) var(--space-large);
      border-radius: var(--border-radius-medium, 8px);
      background: var(--background-color-canvas);
    }
    .head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: var(--space-small);
    }
    .title {
      display: flex;
      align-items: center;
      gap: var(--space-xsmall);
      font-weight: 600;
    }
    .message {
      margin: 0;
      font-size: 0.85rem;
      color: var(--text-color-deemphasized, GrayText);
    }
    .foot {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: var(--space-xsmall);
      font-size: 0.8rem;
      color: var(--text-color-deemphasized, GrayText);
    }
  `;

  render() {
    const u = this.item;
    return html`
      <div class="card">
        <div class="head">
          <span class="title">
            <moz-status-dot
              icon
              type=${u.approved ? 'success' : 'warning'}
            ></moz-status-dot>
            ${u.title}
          </span>
          <moz-button size="small">View</moz-button>
        </div>
        <p class="message">${u.message}</p>
        <div class="foot">
          <span>Version ${u.version}</span>
          <moz-status-badge type=${u.approved ? 'success' : 'warning'}>
            ${u.versionStatus}
          </moz-status-badge>
          ${u.tags.map((t) => html`<span>${t}</span>`)}
          <span>${u.date}</span>
        </div>
      </div>
    `;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'update-card': UpdateCard;
  }
}
