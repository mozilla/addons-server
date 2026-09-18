import { css, html, LitElement } from 'lit';
import { customElement } from 'lit/decorators.js';

@customElement('app-stack')
export class AppStack extends LitElement {
  static styles = css`
    :host {
      display: flex;
      flex-direction: column;
      gap: var(--space-medium);
    }
    :host([gap='small']) {
      gap: var(--space-small);
    }
    :host([gap='large']) {
      gap: var(--space-large);
    }
    :host([gap='xlarge']) {
      gap: var(--space-xlarge);
    }
  `;

  render() {
    return html`<slot></slot>`;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'app-stack': AppStack;
  }
}
