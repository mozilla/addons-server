// URLPattern isn't in every browser yet (Firefox/Safari only added it recently);
// the polyfill is a no-op where it's native. Must load before the Router is built.
import 'urlpattern-polyfill';

import { Router } from '@lit-labs/router';
import { css, html, LitElement } from 'lit';
import { customElement } from 'lit/decorators.js';

import './foundations/acorn';
import './foundations/layout';
// After foundations/acorn so it overrides acorn's base.css :root color-scheme.
import './app.css';

import './devhub/devhub-home';
import './devhub/devhub-addon';

// The SPA is mounted under /pinguino/, so routes match against that prefix.
const BASE = '/pinguino';

// The Router intercepts same-origin <a> clicks (across shadow DOM) and syncs
// history, so views navigate with plain links instead of manual push/goto.
@customElement('pinguino-app')
export class PinguinoApp extends LitElement {
  static styles = css`
    :host {
      display: block;
    }

    /* acorn's moz-provider is display:contents; give it a box so it can fill
     * the viewport height. */
    moz-provider {
      display: block;
      min-height: 100vh;
    }
  `;

  private _router = new Router(
    this,
    [
      { path: `${BASE}/`, render: () => html`<devhub-home></devhub-home>` },
      {
        path: `${BASE}/addon/:slug`,
        render: ({ slug }) =>
          html`<devhub-addon .slug=${slug ?? ''}></devhub-addon>`,
      },
    ],
    {
      fallback: {
        render: () =>
          html`<p>Not found. <a href="${BASE}/">Back to home</a></p>`,
      },
    },
  );

  render() {
    return html`
      <moz-provider>
        <app-container>${this._router.outlet()}</app-container>
      </moz-provider>
    `;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'pinguino-app': PinguinoApp;
  }
}
