import { html, LitElement } from 'lit';
import { customElement, property } from 'lit/decorators.js';

@customElement('devhub-addon')
export class DevhubAddon extends LitElement {
  @property() slug = '';

  render() {
    return html`
      <p><a href="/pinguino/">&larr; Back to home</a></p>
      <moz-page-header heading=${`Manage: ${this.slug}`}></moz-page-header>
      <moz-card>
        <p>Placeholder detail for <strong>${this.slug}</strong>.</p>
      </moz-card>
    `;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'devhub-addon': DevhubAddon;
  }
}
