import { css, html, LitElement } from 'lit';
import { customElement } from 'lit/decorators.js';
import kitSubmit from './img/firefox_motion_off_switch.gif';

@customElement('submit-finish')
export class SubmitFinish extends LitElement {
  static styles = css`
    :host {
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: var(--space-xlarge);
      text-align: center;
    }
    h2 {
      margin: 0;
    }
    p {
      margin: var(--space-xsmall) 0 0;
      font-size: var(--font-size-small);
    }
    #kit-submit {
      width: 25em;
      padding: var(--space-xlarge);
    }
  `;

  render() {
    return html`
      <div>
        <h2>Congrats, your version is submitted</h2>
        <p>You will be able to see the submitted add-ons on the main dashboard</p>
      </div>
      <img id="kit-submit" src=${kitSubmit} alt="" />
      <moz-button variant="primary" size="medium">
        Go to the dashboard
      </moz-button>
    `;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'submit-finish': SubmitFinish;
  }
}
