import { css, html, LitElement } from 'lit';
import { customElement } from 'lit/decorators.js';
import { BASE } from '../base';
import { switchToClassic } from '../switch-back';

@customElement('switch-back-link')
export class SwitchBackLink extends LitElement {
  static styles = css`
    :host {
      display: inline;
    }
    /* Inherit colour and size so the link blends into whatever surrounds it. */
    a {
      color: inherit;
      font-size: inherit;
      text-decoration: none;
    }
    a:hover {
      text-decoration: underline;
    }
  `;

  render() {
    // href carries the path for no-JS / copy / middle-click
    return html`<a
      rel="external"
      href="${BASE}/switch-pinguino"
      @click=${switchToClassic}
      ><slot>Switch back</slot></a
    >`;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'switch-back-link': SwitchBackLink;
  }
}
