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
    .dot {
      width: 0.6rem;
      height: 0.6rem;
      border-radius: 999px;
    }
    .dot.ok {
      background: var(--color-green-50, #2ac3a2);
    }
    .dot.flagged {
      background: var(--color-orange-50, #e49c49);
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
            <!-- TODO: use status-dot component -->
            <span class="dot ${u.approved ? 'ok' : 'flagged'}"></span>
            ${u.title}
          </span>
          <moz-button size="small">View</moz-button>
        </div>
        <p class="message">${u.message}</p>
        <div class="foot">
          <span>Version ${u.version}</span>
          <!-- TODO: switch to a status-badge component -->
          <moz-badge type=${u.approved ? 'success' : 'warning'}>
            ${u.versionStatus}
          </moz-badge>
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
