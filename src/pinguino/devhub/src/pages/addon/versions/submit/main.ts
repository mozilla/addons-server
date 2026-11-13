import { Routes } from '@lit-labs/router';
import { html, LitElement } from 'lit';
import { customElement, property } from 'lit/decorators.js';
import { hasReadAgreement } from '../../../../data/queries';
import { navigateTo } from '../../../../utils/helper';

import '../../submit/templates/agreement';
import './version-submission';

@customElement('version-submit-routes')
class VersionSubmitRoutes extends LitElement {
  @property() slug = '';

  private _routes: Routes = new Routes(this, [
    {
      path: 'agreement',
      enter: async () =>
        !(await hasReadAgreement().catch(() => false)) ||
        navigateTo('', { routes: this._routes, replace: true }),
      render: () =>
        html`<devhub-agreement .next=${this._routes.link('')}></devhub-agreement>`,
    },
    {
      path: '*',
      enter: async () =>
        (await hasReadAgreement()) ||
        navigateTo('agreement', { routes: this._routes, replace: true }),
      render: () =>
        html`<version-submission .slug=${this.slug}></version-submission>`,
    },
  ]);

  render() {
    return this._routes.outlet();
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'version-submit-routes': VersionSubmitRoutes;
  }
}
