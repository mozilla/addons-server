import { Routes } from '@lit-labs/router';
import { html, LitElement } from 'lit';
import { customElement } from 'lit/decorators.js';

import './submit/main';
import './templates/devhub-addon';
import './versions/main';

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
      path: ':slug/versions/*',
      render: ({ slug }) =>
        html`<version-routes .slug=${slug ?? ''}></version-routes>`,
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
