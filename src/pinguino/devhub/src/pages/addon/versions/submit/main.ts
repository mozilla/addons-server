import { Routes } from '@lit-labs/router';
import { html, LitElement } from 'lit';
import { customElement, property } from 'lit/decorators.js';
import { fetchAgreement } from '../../../../data/api';
import { queryKeys } from '../../../../data/queries';
import { queryClient } from '../../../../data/query-client';
import { navigateTo } from '../../../../helper';

import '../../submit/submission-flow';
import '../../submit/templates/agreement';
import '../../submit/templates/distribution';
import '../../submit/templates/finish';
import '../../submit/templates/review';
import '../../submit/templates/source';
import '../../submit/templates/upload';

@customElement('version-submit-routes')
class VersionSubmitRoutes extends LitElement {
  @property() slug = '';

  private _routes: Routes = new Routes(this, [
    {
      path: 'agreement',
      render: () =>
        html`<devhub-agreement .next=${this._routes.link('')}></devhub-agreement>`,
    },
    {
      path: '*',
      enter: async () =>
        (
          await queryClient.query({
            queryKey: queryKeys.agreement,
            queryFn: fetchAgreement,
            staleTime: 'static',
          })
        ).has_read_developer_agreement ||
        navigateTo('agreement', { routes: this._routes, replace: true }),
      render: () =>
        html`<addon-submission .slug=${this.slug}></addon-submission>`,
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
