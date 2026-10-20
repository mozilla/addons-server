import { css, html, LitElement, nothing } from 'lit';
import { customElement, property, query, state } from 'lit/decorators.js';
import { LOCALE } from '../base';
import type { Developer } from '../data';
import { logout } from '../data';

// The user's AMO profile page lives on the frontend. Prefix the locale when we
// have one; omit it entirely otherwise (no empty segment / double slash).
const profileUrl = (id: string) =>
  `${LOCALE ? `/${LOCALE}` : ''}/firefox/user/${id}/`;

// Avatar trigger plus the dropdown menu shown to a signed-in developer. The
// header owns the signed-in/out decision and passes the resolved `profile` in.
@customElement('devhub-account-menu')
export class DevhubAccountMenu extends LitElement {
  static styles = css`
    :host {
      display: inline-flex;
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

  // The signed-in developer this renders the avatar and menu for.
  @property({ attribute: false }) profile!: Developer;

  // Reflects whether the account dropdown is open.
  @state() private open = false;

  @query('.trigger') private triggerButton?: HTMLButtonElement;

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

  render() {
    const profile = this.profile;
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
}

declare global {
  interface HTMLElementTagNameMap {
    'devhub-account-menu': DevhubAccountMenu;
  }
}
