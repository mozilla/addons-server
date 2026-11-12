import { Routes } from '@lit-labs/router';
import { customElement } from 'lit/decorators.js';

import '../../../components/coming-soon';
import './templates/agreement';

import { html, LitElement } from 'lit';

@customElement('submit-routes')
class SubmitRoutes extends LitElement {
  private _routes = new Routes(this, [
    {
      path: 'agreement',
      render: () => html`<devhub-agreement></devhub-agreement>`,
    },
    // Theme submission isn't reimplemented yet
    {
      path: 'theme/agreement{/}?',
      render: () => html`<coming-soon></coming-soon>`,
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
