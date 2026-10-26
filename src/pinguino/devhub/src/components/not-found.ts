import { html, LitElement } from 'lit';
import { customElement } from 'lit/decorators.js';

@customElement('not-found')
export class NotFound extends LitElement {
  render() {
    return html`<p>Not found. <a href="/developers/">Back to home</a></p>`;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'not-found': NotFound;
  }
}
