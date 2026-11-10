import { Routes } from '@lit-labs/router';
import { html, LitElement } from 'lit';
import { customElement, property } from 'lit/decorators.js';
import { hasReadAgreement } from '../../../data/queries';
import { navigateTo } from '../../../utils/helper';

import './addon-submission';
import './templates/agreement';

@customElement('submit-routes')
class SubmitRoutes extends LitElement {
  @property() slug = '';

  private _routes: Routes = new Routes(this, [
    {
      path: 'agreement',
      enter: () => this.unlessAccepted('distribution'),
      render: () => this.agreement('distribution'),
    },
    {
      path: 'theme/agreement',
      enter: () => this.unlessAccepted('theme/distribution'),
      render: () => this.agreement('theme/distribution'),
    },
    {
      path: '*',
      enter: async ({ 0: step = '' }) =>
        Boolean(this.slug) ||
        (await hasReadAgreement()) ||
        navigateTo(
          step.startsWith('theme/') ? 'theme/agreement' : 'agreement',
          { routes: this._routes, replace: true },
        ),
      render: () =>
        html`<addon-submission .slug=${this.slug}></addon-submission>`,
    },
  ]);

  private async unlessAccepted(next: string) {
    return (
      !(await hasReadAgreement().catch(() => false)) ||
      navigateTo(next, { routes: this._routes, replace: true })
    );
  }

  private agreement(next: string) {
    return html`<devhub-agreement
      .next=${this._routes.link(next)}
    ></devhub-agreement>`;
  }

  render() {
    return this._routes.outlet();
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'submit-routes': SubmitRoutes;
  }
}
