import { css, html, LitElement, nothing } from 'lit';
import { customElement, query, state } from 'lit/decorators.js';
import { BASE, LOCALE } from '../base';
import type { Developer } from '../data';
import { logout, profileQuery } from '../data';

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

// The user's AMO profile page lives on the frontend
const profileUrl = (id: string) => `/${LOCALE ? LOCALE + '/' : ''}/firefox/user/${id}/`;

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
    .account {
      position: relative;
      display: inline-flex;
    }
    .trigger {
      display: inline-flex;
      align-items: center;
      padding: 0;
      border: none;
      border-radius: 50%;
      background: none;
      color: inherit;
      cursor: pointer;
    }
    .avatar {
      display: block;
      width: 32px;
      height: 32px;
      border-radius: 50%;
      /* Crop (not squash) non-square images into the circle. */
      object-fit: cover;
    }
    /* Initials circle shown only when a picture_url is missing. */
    .avatar--fallback {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      font-size: 0.8rem;
      font-weight: 600;
      background: light-dark(rgba(21, 20, 26, 0.1), rgba(251, 251, 254, 0.16));
    }
    .menu {
      position: absolute;
      inset-block-start: calc(100% + var(--space-xsmall));
      inset-inline-end: 0;
      z-index: 10;
      display: flex;
      flex-direction: column;
      min-width: 10rem;
      padding: var(--space-xsmall);
      background: light-dark(Canvas, #1c1b22);
      border: 1px solid
        light-dark(rgba(21, 20, 26, 0.12), rgba(251, 251, 254, 0.16));
      border-radius: 4px;
      box-shadow: 0 2px 8px rgba(0, 0, 0, 0.2);
    }
    .menu [role='menuitem'] {
      display: block;
      padding: var(--space-xsmall) var(--space-small);
      border: none;
      border-radius: 4px;
      background: none;
      color: inherit;
      font: inherit;
      font-size: 0.9rem;
      text-align: start;
      text-decoration: none;
      white-space: nowrap;
      cursor: pointer;
    }
    .menu [role='menuitem']:hover {
      text-decoration: none;
      background: light-dark(rgba(21, 20, 26, 0.06), rgba(251, 251, 254, 0.1));
    }
  `;

  // Reflects whether the account dropdown is open; only meaningful when signed in.
  @state() private open = false;

  @query('.trigger') private triggerButton?: HTMLButtonElement;

  // Signed-in developer, session-lived. data present => signed in; no data (and
  // not loading) => signed out, since the profile can't be fetched without a
  // session.
  #profile = profileQuery(this);

  connectedCallback() {
    super.connectedCallback();
    window.addEventListener('click', this.#onDocumentClick);
    this.addEventListener('keydown', this.#onKeydown);
  }

  disconnectedCallback() {
    window.removeEventListener('click', this.#onDocumentClick);
    this.removeEventListener('keydown', this.#onKeydown);
    super.disconnectedCallback();
  }

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

  #toggleMenu = () => {
    this.open = !this.open;
  };

  // Close on any click outside the host (composedPath pierces the shadow root).
  #onDocumentClick = (event: MouseEvent) => {
    if (this.open && !event.composedPath().includes(this)) {
      this.open = false;
    }
  };

  #onKeydown = (event: KeyboardEvent) => {
    if (event.key === 'Escape' && this.open) {
      this.open = false;
      this.triggerButton?.focus();
    }
  };

  // Log out by ending the session server-side, then reload so everything is rebuilt as
  // signed-out. Reload even if the request fails - the session may already be gone.
  #logout = async (event: Event) => {
    event.preventDefault();
    try {
      await logout();
    } finally {
      location.reload();
    }
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

  #accountMenu(profile: Developer) {
    return html`
      <div class="account">
        <button
          class="trigger"
          aria-haspopup="menu"
          aria-expanded=${this.open}
          aria-label="Account menu"
          @click=${this.#toggleMenu}
        >
          ${
            profile.pictureUrl
              ? html`<img class="avatar" src="${profile.pictureUrl}" alt="" />`
              : html`<span class="avatar avatar--fallback"
                  >${(profile.name || '?').charAt(0).toUpperCase()}</span
                >`
          }
        </button>
        ${
          this.open
            ? html`
              <div class="menu" role="menu">
                <a role="menuitem" class="profile" href="${profileUrl(profile.id)}"
                  >${profile.name || 'Profile'}</a
                >
                <button role="menuitem" class="logout" @click=${this.#logout}>
                  Log out
                </button>
              </div>
            `
            : nothing
        }
      </div>
    `;
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
              ? this.#accountMenu(profile.data)
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
