import { html, LitElement } from 'lit';
import { customElement } from 'lit/decorators.js';

// Placeholder for devhub pages that exist in the Django app but haven't been
// reimplemented in Pinguino yet, so old bookmarks land somewhere sensible
// instead of a "Not found" page.
@customElement('coming-soon')
export class ComingSoon extends LitElement {
  render() {
    return html`<p>Coming soon.</p>`;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'coming-soon': ComingSoon;
  }
}
