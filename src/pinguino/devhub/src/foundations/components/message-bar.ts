import { css, html, LitElement } from 'lit';
import { customElement, property } from 'lit/decorators.js';

@customElement('message-bar')
export class MessageBar extends LitElement {
  static styles = css`
    :host {
      display: block;
    }
    legend {
      padding: 0;
      font-weight: var(--font-weight-heading);
    }
    .description {
      margin: 0;
      padding: 0;
    }
    .message-content {
      padding: var(--space-xsmall);
    }
    .text-content {
      margin: 0;
      padding: 0;
    }
    moz-message-bar {
      --message-bar-content-gap: 0 var(--space-medium);
    }
  `;

  @property() type = 'info';
  @property() heading = '';
  @property() description = '';

  render() {
    return html`
      <moz-message-bar type=${this.type}>
        <div class="message-content">
          <legend>${this.heading}</legend>
          <div class="description">${this.description}<slot></slot></div>
        </div>
      </moz-message-bar>
    `;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'message-bar': MessageBar;
  }
}
