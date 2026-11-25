import { html, LitElement } from 'lit';
import { customElement } from 'lit/decorators.js';
import './switch-back-link';

// Placeholder for devhub pages that exist in the Django app but haven't been
// reimplemented in Pinguino yet, so old bookmarks land somewhere sensible
// instead of a "Not found" page.
@customElement('coming-soon')
export class ComingSoon extends LitElement {
  render() {
    return html`<p>
      This feature is not implemented in the new Developer Hub yet, for now you
      can <switch-back-link>access this feature in the previous version</switch-back-link>.
    </p>`;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'coming-soon': ComingSoon;
  }
}
