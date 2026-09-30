// acorn's component tokens are :host-scoped, so adopt the sheet into this
// component's shadow root — a plain global import would leave :host matching
// nothing. `?inline` gives the CSS as a string instead of injecting it.
import buttonTokens from '@mozilla/acorn-web-components/tokens/button.css?inline';
import { css, html, LitElement, unsafeCSS } from 'lit';
import { customElement, property } from 'lit/decorators.js';

@customElement('submit-card')
export class SubmitCard extends LitElement {
  @property() label = 'Submit new extension';

  static styles = [
    unsafeCSS(buttonTokens),
    css`
      :host {
        display: block;
        height: 100%;
      }
      button {
        box-sizing: border-box;
        width: 100%;
        height: 100%;
        min-height: 120px;
        display: flex;
        align-items: center;
        justify-content: center;
        gap: var(--space-small);
        padding: var(--space-large);
        font: inherit;
        color: var(--text-color-deemphasized, GrayText);
        background: transparent;
        border: 1px dashed
          light-dark(rgba(21, 20, 26, 0.3), rgba(251, 251, 254, 0.3));
        border-radius: var(--border-radius-medium, 8px);
        cursor: pointer;
      }
      button:hover {
        background: light-dark(
          rgba(21, 20, 26, 0.03),
          rgba(251, 251, 254, 0.06)
        );
      }

      moz-icon {
        border-radius: 50%;
        padding: var(--space-xxsmall);
        background-color: var(--button-background-color-primary);
        color: var(--button-text-color-primary);
      }
    `,
  ];

  render() {
    return html`
      <button type="button">
        <moz-icon name="add"></moz-icon>
        ${this.label}
      </button>
    `;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'submit-card': SubmitCard;
  }
}
