import { html, LitElement, nothing } from 'lit';
import { customElement, property } from 'lit/decorators.js';
import { addonQuery } from '../../../data';
import { createRoutes } from '../../../helper';

import '../../../components/coming-soon';
import '../../../components/error-page';
import './submit/main';

@customElement('version-routes')
class VersionRoutes extends LitElement {
  @property() slug = '';

  #addon = addonQuery(this, () => this.slug);

  private _routes = createRoutes(this, [
    {
      path: 'submit/*',
      render: () =>
        html`<version-submit-routes .slug=${this.slug}></version-submit-routes>`,
    },
    { path: ':versionId', render: () => html`<coming-soon></coming-soon>` },
  ]);

  render() {
    const addon = this.#addon();
    if (addon.isPending) return nothing;
    if (addon.isSuccess && !addon.data) return html`<error-page></error-page>`;
    return this._routes.outlet();
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'version-routes': VersionRoutes;
  }
}
