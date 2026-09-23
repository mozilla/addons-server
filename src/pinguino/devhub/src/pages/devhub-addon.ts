import { html, LitElement } from 'lit';
import { customElement, property } from 'lit/decorators.js';
import { addonQuery } from '../data';

@customElement('devhub-addon')
export class DevhubAddon extends LitElement {
  @property() slug = '';

  // Served from the dashboard's cached add-on list, so arriving here shows the
  // name immediately with no extra request.
  #addon = addonQuery(this, () => this.slug);

  render() {
    const name = this.#addon().data?.name ?? this.slug;
    return html`
      <p><a href="/pinguino/">&larr; Back to home</a></p>
      <moz-page-header heading=${`Manage: ${name}`}></moz-page-header>
      <moz-card>
        <p>Placeholder detail for <strong>${name}</strong>.</p>
      </moz-card>
    `;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'devhub-addon': DevhubAddon;
  }
}
