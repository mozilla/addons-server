import { Routes } from '@lit-labs/router';
import { html, LitElement } from 'lit';
import { customElement } from 'lit/decorators.js';

import './submit/main';
import './templates/devhub-addon';

@customElement('addon-routes')
class AddonRoutes extends LitElement {
  private _routes = new Routes(this, [
    { path: 'submit/*', render: () => html`<submit-routes></submit-routes>` },
    {
      path: `:slug`,
      render: ({ slug }) =>
        html`<devhub-addon .slug=${slug ?? ''}></devhub-addon>`,
    },
    {
      path: `:slug/:tab`,
      render: ({ slug, tab }) =>
        html`<devhub-addon .slug=${slug ?? ''} .tab=${tab ?? ''}></devhub-addon>`,
    },
  ]);
  render() {
    return this._routes.outlet();
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'addon-routes': AddonRoutes;
  }
}
