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

import './components/devhub-header';
import './pages/devhub-home';
import './pages/addon/main';
import './pages/addon/templates/devhub-addon';

import { BASE } from './base';
import { interceptOutOfAppLinks, pageParam } from './navigation';

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
        path: `${BASE}/addon/*`,
        render: () => html`<addon-routes></addon-routes>`,
      },
      // The legacy DevHub's per-add-on feed URL, kept working by rendering the
      // same add-on shell with the feed tab active.
      {
        path: `${BASE}/feed/:slug`,
        render: ({ slug }) =>
          html`<devhub-addon
            .slug=${slug ?? ''}
            tab="feed"
            .page=${pageParam()}
          ></devhub-addon>`,
      },
    ],
    {
      fallback: {
        render: () =>
          html`<p>Not found. <a href="${BASE}">Back to home</a></p>`,
      },
    },
  );

  #cleanupLinks?: () => void;

  connectedCallback() {
    super.connectedCallback();
    this.#cleanupLinks = interceptOutOfAppLinks(BASE);
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    this.#cleanupLinks?.();
  }

  render() {
    return html`
      <moz-provider>
        <!-- TODO: implement proper page header/navigation -->
        <devhub-header></devhub-header>
        <app-container>${this._router.outlet()}</app-container>
      </moz-provider>
    `;
  }
}

if (import.meta.env.DEV) {
  import('./data/devtools').then((m) => m.mountDevtools());
}

declare global {
  interface HTMLElementTagNameMap {
    'pinguino-app': PinguinoApp;
  }
}
