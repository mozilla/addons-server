import { html, LitElement } from 'lit';
import { customElement } from 'lit/decorators.js';
import { setPageTitle } from '../page-title';

@customElement('not-found')
export class NotFound extends LitElement {
  updated() {
    setPageTitle(['Page not found']);
  }

  render() {
    return html`<p>Not found. <a href="/developers/">Back to home</a></p>`;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'not-found': NotFound;
  }
}
