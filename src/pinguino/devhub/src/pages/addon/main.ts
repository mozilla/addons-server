import { Routes } from '@lit-labs/router';
import { html, LitElement } from 'lit';
import { customElement } from 'lit/decorators.js';

import { BASE } from '../../base';
import '../../components/coming-soon';
import './submit/main';
import './templates/devhub-addon';
import './versions/main';
import { navigateTo } from '../../helper';

@customElement('addon-routes')
class AddonRoutes extends LitElement {
  private _routes = new Routes(this, [
    { path: 'submit/*', render: () => html`<submit-routes></submit-routes>` },
    // Top-level add-on pages not yet reimplemented
    { path: 'api/key{/}?', render: () => html`<coming-soon></coming-soon>` },
    { path: 'validate{/}?', render: () => html`<coming-soon></coming-soon>` },
    {
      path: `:slug`,
      enter: ({ slug }) => navigateTo(`${slug}/edit`, { replace: true }),
    },
    {
      path: ':slug/versions/*',
      render: ({ slug }) =>
        html`<version-routes .slug=${slug ?? ''}></version-routes>`,
    },
    // Django's /ownership page is the authors section of the edit tab.
    {
      path: ':slug/ownership',
      enter: ({ slug }) =>
        navigateTo(`${BASE}/addon/${slug}/edit/authors`, { replace: true }),
    },
    {
      path: `:slug/:tab`,
      render: ({ slug, tab }) =>
        html`<devhub-addon .slug=${slug ?? ''} .tab=${tab ?? ''}></devhub-addon>`,
    },
    {
      path: `:slug/:tab/:section`,
      render: ({ slug, tab, section }) =>
        html`<devhub-addon
          .slug=${slug ?? ''}
          .tab=${tab ?? ''}
          .section=${section ?? ''}
        ></devhub-addon>`,
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
