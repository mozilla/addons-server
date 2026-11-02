import { css, html, LitElement } from 'lit';
import { customElement, property } from 'lit/decorators.js';
import { LOCALE } from '../base';
import type { Developer } from '../data';
import { logout } from '../data';

// The user's AMO profile page lives on the frontend. Prefix the locale when we
// have one; omit it entirely otherwise (no empty segment / double slash).
const profileUrl = (id: string) =>
  `${LOCALE ? `/${LOCALE}` : ''}/firefox/user/${id}/`;

// An account avatar plus dropdown menu, show for logged-in developers.
@customElement('devhub-account-menu')
export class DevhubAccountMenu extends LitElement {
  static styles = css`
    :host {
      display: inline-flex;
    }
    .trigger::part(button) {
      padding: 0;
      min-width: auto;
      // Make the button circular like the avatar inside.
      border-radius: 50%;
    }
    .avatar {
      display: block;
      width: 32px;
      height: 32px;
      border-radius: 50%;
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
  `;

  @property({ attribute: false }) profile!: Developer;

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
      <moz-button
        class="trigger"
        variant="ghost"
        icon-only="account"
        menu-id="account-menu"
      >
        ${
          profile.pictureUrl
            ? html`<img class="avatar" src="${profile.pictureUrl}" alt="" />`
            : html`<span class="avatar avatar--fallback"
                >${(profile.name || '?').charAt(0).toUpperCase()}</span
              >`
        }
      </moz-button>
      <moz-panel-list id="account-menu" label="${profile.name || 'Account'}">
        <moz-panel-item class="profile" href="${profileUrl(profile.id)}"
          >${profile.name || 'Profile'}</moz-panel-item
        >
        <moz-panel-item class="logout" @click=${this.#logout}
          >Log out</moz-panel-item
        >
      </moz-panel-list>
    `;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'devhub-account-menu': DevhubAccountMenu;
  }
}
