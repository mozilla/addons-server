import { css, html, LitElement } from 'lit';
import { customElement } from 'lit/decorators.js';

@customElement('app-container')
export class AppContainer extends LitElement {
  static styles = css`
    :host {
      display: block;
      box-sizing: border-box;
      max-width: 1280px;
      margin-inline: auto;
      padding-inline: var(--space-xlarge);
    }
    :host([size='small']) {
      max-width: 640px;
    }
    :host([size='medium']) {
      max-width: 800px;
    }
    :host([size='large']) {
      max-width: 1024px;
    }
    :host([size='xlarge']) {
      max-width: 1280px;
    }
  `;

  render() {
    return html`<slot></slot>`;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'app-container': AppContainer;
  }
}
