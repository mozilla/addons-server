import { css, html, LitElement, nothing } from 'lit';
import { customElement } from 'lit/decorators.js';
import { BASE } from '../base';
import { profileQuery } from '../data';
import './devhub-account-menu';

const NAV = [
  'My Add-ons',
  'Documentation',
  'Tools',
  'Community & Support',
  'Extension Workshop',
];

// Starts the FxA login flow, returning the user to `path` afterwards.
const loginUrl = (path: string) =>
  `/api/v5/accounts/login/start/?to=${encodeURIComponent(path)}`;

@customElement('devhub-header')
export class DevhubHeader extends LitElement {
  static styles = css`
    :host {
      display: block;
      border-bottom: 1px solid
        light-dark(rgba(21, 20, 26, 0.12), rgba(251, 251, 254, 0.16));
    }
    .bar {
      display: flex;
      align-items: center;
      gap: var(--space-large);
      padding-block: var(--space-medium);
      margin: 0 1em;
    }
    .brand {
      font-weight: 700;
    }
    nav {
      display: flex;
      flex-wrap: wrap;
      gap: var(--space-large);
    }
    a {
      color: var(--text-color, CanvasText);
      text-decoration: none;
      font-size: 0.9rem;
    }
    a:hover {
      text-decoration: underline;
    }
    .spacer {
      margin-inline-start: auto;
    }
  `;

  // Signed-in developer, session-lived. data present => signed in; no data (and
  // not loading) => signed out, since the profile can't be fetched without a
  // session.
  #profile = profileQuery(this);

  // Switch to the classic devhub via the Django endpoint that flips the PINGUINO
  // cookie; the bare href is a no-JS fallback (view defaults to the index).
  #switchToClassic = (event: Event) => {
    event.preventDefault();
    const path = location.pathname + location.search;
    location.href = `${BASE}/switch-pinguino?path=${encodeURIComponent(path)}`;
  };

  // Navigate to the login flow, using the current location.
  #login = (event: Event) => {
    event.preventDefault();
    location.href = loginUrl(location.pathname + location.search);
  };

  #loginLink() {
    // href carries the return path for no-JS / copy / middle-click
    return html`<a
      class="login"
      href="${loginUrl(location.pathname + location.search)}"
      @click=${this.#login}
      >Log in</a
    >`;
  }

  render() {
    const profile = this.#profile();
    return html`
      <div class="bar">
        <a class="brand" href="${BASE}/">Add-ons</a>
        <nav>
          ${NAV.map((label) => html`<a href="${BASE}/">${label}</a>`)}
          <a
            rel="external"
            href="${BASE}/switch-pinguino"
            @click=${this.#switchToClassic}
            >Switch back to the old Developer Hub</a
          >
        </nav>
        <span class="spacer"></span>
        ${
          profile.isPending
            ? nothing
            : profile.data
              ? html`<devhub-account-menu
                  .profile=${profile.data}
                ></devhub-account-menu>`
              : this.#loginLink()
        }
      </div>
    `;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'devhub-header': DevhubHeader;
  }
}
