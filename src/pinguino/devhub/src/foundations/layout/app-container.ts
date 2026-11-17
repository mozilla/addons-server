import { css, html, LitElement } from 'lit';
import { customElement } from 'lit/decorators.js';

@customElement('app-container')
export class AppContainer extends LitElement {
  static styles = css`
    :host {
      /* A column so a view can claim the leftover height with flex-grow. A
       * percentage can't: this element's own height isn't definite. */
      display: flex;
      flex-direction: column;
      box-sizing: border-box;
      max-width: 1280px;
      /* As a flex/grid item the auto margins would otherwise suppress the
       * stretch and shrink this to its content; an explicit width keeps the
       * max-width + auto-margin centring working in any parent. */
      width: 100%;
      margin-inline: auto;
      padding-inline: var(--space-xlarge);
      /* Breathing room at the bottom once content grows past the shell's 100vh
       * floor. The floor lives on moz-provider, so this adds no always-on scroll. */
      padding-block-end: var(--size-layout-xsmall);
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
