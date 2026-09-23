import { css, html, LitElement } from 'lit';
import { customElement } from 'lit/decorators.js';

@customElement('devhub-home')
export class DevhubHome extends LitElement {
  static styles = css`
    /* Once the grid stacks (default break is md), show "Getting started" above
     * the main column. */
    @container app-grid (max-width: 768px) {
      .sidebar {
        order: -1;
      }
    }
  `;

  render() {
    return html`
      <app-stack gap="large">
        <moz-page-header heading="Developer Hub"></moz-page-header>

        <app-grid gap="large">
          <moz-card style="grid-column: span 8">
            <p>Your add-ons</p>
            <nav>
              <ul>
                <li><a href="/pinguino/addon/my-first-addon">Manage my-first-addon</a></li>
                <li><a href="/pinguino/addon/another-addon">Manage another-addon</a></li>
              </ul>
            </nav>
            <moz-button variant="primary">Submit a new add-on</moz-button>
          </moz-card>

          <moz-card class="sidebar" style="grid-column: span 4">
            <p>Getting started</p>
          </moz-card>
        </app-grid>
      </app-stack>
    `;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'devhub-home': DevhubHome;
  }
}
