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

import './components/coming-soon';
import './components/devhub-header';
import './components/not-found';
import './pages/devhub-home';
import './pages/addon/main';

import { BASE } from './base';
import { navigateTo } from './helper';
import { interceptOutOfAppLinks } from './navigation';
import { recordLanding } from './switch-back';

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
      // The developer dashboard lives at the base path (and has themes too).
      {
        path: `${BASE}{/}?`,
        render: () => html`<devhub-home></devhub-home>`,
      },
      // The old dashboard, themes and /addon(s) URLs redirect to the base.
      {
        path: `${BASE}/addons`,
        enter: () => navigateTo(BASE, { replace: true }),
      },
      {
        path: `${BASE}/themes`,
        enter: () => navigateTo(BASE, { replace: true }),
      },
      // /addon is a typo for /addons, redirect it.
      {
        path: `${BASE}/addon`,
        enter: () => navigateTo(BASE, { replace: true }),
      },
      // /addons/<id>/... paths are a typo for /addon/<id>/...
      {
        path: `${BASE}/addons/*`,
        enter: () =>
          navigateTo(location.pathname.replace('/addons/', '/addon/'), {
            replace: true,
          }),
      },
      {
        path: `${BASE}/addon/*`,
        render: () => html`<addon-routes></addon-routes>`,
      },
      // feeds now live directly on the dashboard, and per add-on feeds live on the /addon/xxx/feed
      {
        path: `${BASE}/feed`,
        enter: () => navigateTo(BASE, { replace: true }),
      },
      {
        path: `${BASE}/feed/:addonId`,
        enter: ({ addonId }) =>
          navigateTo(`${BASE}/addon/${addonId}/feed`, { replace: true }),
      },
      // Top-level pages not yet reimplemented
      {
        path: `${BASE}/support`,
        render: () => html`<coming-soon></coming-soon>`,
      },
      {
        path: `${BASE}/verify-email`,
        render: () => html`<coming-soon></coming-soon>`,
      },
    ],
    {
      fallback: {
        render: () => html`<not-found></not-found>`,
      },
    },
  );

  #cleanupLinks?: () => void;

  connectedCallback() {
    super.connectedCallback();
    // Remember the url we landed on after redirects, for switching back.
    recordLanding();
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
