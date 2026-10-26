import { Routes } from '@lit-labs/router';
import { html, LitElement, nothing } from 'lit';
import { customElement, property } from 'lit/decorators.js';
import { addonQuery } from '../../../data';

import '../../../components/not-found';
import './submit/main';

@customElement('version-routes')
class VersionRoutes extends LitElement {
  @property() slug = '';

  #addon = addonQuery(this, () => this.slug);

  private _routes = new Routes(this, [
    {
      path: 'submit/*',
      render: () =>
        html`<version-submit-routes .slug=${this.slug}></version-submit-routes>`,
    },
  ]);

  render() {
    const addon = this.#addon();
    if (addon.isPending) return nothing;
    if (addon.isSuccess && !addon.data) return html`<not-found></not-found>`;
    return this._routes.outlet();
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'version-routes': VersionRoutes;
  }
}
