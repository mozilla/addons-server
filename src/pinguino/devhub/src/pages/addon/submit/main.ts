import { Routes } from '@lit-labs/router';
import { customElement } from 'lit/decorators.js';

import './templates/agreement';

import { html, LitElement } from 'lit';

@customElement('submit-routes')
class SubmitRoutes extends LitElement {
  private _routes = new Routes(this, [
    {
      path: 'agreement',
      render: () => html`<devhub-agreement></devhub-agreement>`,
    },
  ]);
  render() {
    return this._routes.outlet();
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'submit-routes': SubmitRoutes;
  }
}
