import { css, html, LitElement, nothing, type TemplateResult } from 'lit';
import { customElement } from 'lit/decorators.js';
import { BASE } from '../base';
import { type Addon, addonsQuery, profileQuery } from '../data';
import { ADDONS_BLOG, ADDONS_FORUM, extensionWorkshop } from '../links';
import { switchBackPath } from '../switch-back';
import './devhub-account-menu';

interface NavItem {
  label: string;
  href: string;
  external?: boolean;
}

interface NavMenu {
  /** Scoped to this shadow root; moz-button resolves it via getRootNode(). */
  id: string;
  label: string;
  items: NavItem[];
}

// Past this the menu stops being a menu, so the rest live on the dashboard.
const MAX_ADDONS = 7;

const MENUS: NavMenu[] = [
  {
    id: 'nav-documentation',
    label: 'Documentation',
    items: [
      {
        label: 'Extension Development',
        href: extensionWorkshop('/documentation/develop/'),
        external: true,
      },
      {
        label: 'Themes',
        href: extensionWorkshop('/documentation/themes/'),
        external: true,
      },
      {
        label: 'Developer Policies',
        href: extensionWorkshop('/documentation/publish/add-on-policies/'),
        external: true,
      },
    ],
  },
  {
    id: 'nav-tools',
    label: 'Tools',
    items: [
      { label: 'Add-on Validator', href: `${BASE}/addon/validate` },
      { label: 'Manage API Keys', href: `${BASE}/addon/api/key` },
    ],
  },
  {
    id: 'nav-community',
    label: 'Community & Support',
    items: [
      { label: 'Add-on Blog', href: ADDONS_BLOG, external: true },
      { label: 'Add-on Forum', href: ADDONS_FORUM, external: true },
      { label: 'Contact Support', href: `${BASE}/support` },
    ],
  },
  // The design gives Extension Workshop a menu but doesn't say what's in it;
  // these mirror the site's own sections until UX fills the gap.
  {
    id: 'nav-workshop',
    label: 'Extension Workshop',
    items: [
      {
        label: 'Extension Workshop Home',
        href: extensionWorkshop(),
        external: true,
      },
      {
        label: 'Publishing Guide',
        href: extensionWorkshop('/documentation/publish/'),
        external: true,
      },
      {
        label: 'Managing Your Add-ons',
        href: extensionWorkshop('/documentation/manage/'),
        external: true,
      },
      {
        label: 'Get in Touch',
        href: extensionWorkshop('/', '#connect'),
        external: true,
      },
    ],
  },
];

// Starts the FxA login flow, returning the user to `path` afterwards.
const loginUrl = (path: string) =>
  `/api/v5/accounts/login/start/?to=${encodeURIComponent(path)}`;

@customElement('devhub-header')
export class DevhubHeader extends LitElement {
  static styles = css`
    :host {
      display: block;
      background-color: var(--background-color-box);
    }
    .bar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: var(--space-large);
      padding-block: var(--space-large);
      padding-inline: var(--space-large) var(--space-xlarge);
    }
    .brand {
      display: flex;
      align-items: center;
      gap: var(--space-small);
      padding-inline-start: var(--space-small);
      color: var(--text-color, CanvasText);
      font-size: var(--font-size-heading-large);
      font-weight: 600;
      text-decoration: none;
    }
    .brand moz-icon {
      --icon-size: 40px;
    }
    nav {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      /* The design spaces labels 32px apart; the triggers contribute 8px of
       * padding each so they have a hit area wider than their text. */
      gap: var(--space-large);
    }
    .trigger::part(button) {
      padding-inline: var(--space-small);
      font-weight: 400;
    }
    a {
      color: var(--text-color, CanvasText);
      text-decoration: none;
      font-size: var(--font-size-root);
    }
    a:hover {
      text-decoration: underline;
    }
    /* Holds the row's height steady while the profile loads, so the bar doesn't
     * jump when the avatar replaces the log-in link. */
    .account {
      display: flex;
      align-items: center;
      justify-content: flex-end;
      min-block-size: var(--size-item-large);
    }
  `;

  // Signed-in developer, session-lived. data present => signed in; no data (and
  // not loading) => signed out, since the profile can't be fetched without a
  // session.
  #profile = profileQuery(this);

  #addons = addonsQuery(this, () => Boolean(this.#profile().data));

  // Switch to the classic devhub via the Django endpoint that flips the PINGUINO
  // cookie; the bare href is a no-JS fallback (view defaults to the index).
  #switchToClassic = (event: Event) => {
    event.preventDefault();
    const path = switchBackPath();
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

  #trigger(id: string, label: string) {
    return html`<moz-button
      class="trigger"
      variant="ghost"
      icon-end="chevron-down"
      menu-id=${id}
      >${label}</moz-button
    >`;
  }

  #item({ label, href, external }: NavItem) {
    return html`<moz-panel-item
      href=${href}
      target=${external ? '_blank' : nothing}
      icon-end=${external ? 'external-link' : nothing}
      >${label}</moz-panel-item
    >`;
  }

  #menu({ id, label, items }: NavMenu): TemplateResult {
    return html`
      ${this.#trigger(id, label)}
      <moz-panel-list id=${id} type="menu" label=${label}>
        <h2>${label}</h2>
        ${items.map((item) => this.#item(item))}
      </moz-panel-list>
    `;
  }

  #myAddonsMenu(): TemplateResult {
    const addons: Addon[] = this.#addons().data ?? [];
    return html`
      ${this.#trigger('nav-my-addons', 'My Add-ons')}
      <moz-panel-list id="nav-my-addons" type="menu" label="My Add-ons">
        <h2>My Add-ons</h2>
        ${addons.slice(0, MAX_ADDONS).map(
          (addon) => html`<moz-panel-item
            icon-start=${addon.kind === 'theme' ? 'themes' : 'extension'}
            href="${BASE}/addon/${addon.slug}"
            >${addon.name}</moz-panel-item
          >`,
        )}
        ${
          addons.length > MAX_ADDONS
            ? html`<moz-panel-item href="${BASE}/"
                >More add-ons…</moz-panel-item
              >`
            : nothing
        }
        <hr />
        <h2>Create New Add-on</h2>
        <moz-panel-item href="${BASE}/addon/submit/agreement"
          >Submit a New Add-on</moz-panel-item
        >
        <moz-panel-item href="${BASE}/addon/submit/theme/agreement"
          >Submit a New Theme</moz-panel-item
        >
      </moz-panel-list>
    `;
  }

  render() {
    const profile = this.#profile();
    return html`
      <div class="bar">
        <a class="brand" href="${BASE}">
          <moz-icon name="logo-firefox"></moz-icon>
          Add-ons
        </a>
        <nav>
          ${profile.data ? this.#myAddonsMenu() : nothing}
          ${MENUS.map((menu) => this.#menu(menu))}
          <a
            rel="external"
            href="${BASE}/switch-pinguino"
            @click=${this.#switchToClassic}
            >Switch back to the old Developer Hub</a
          >
        </nav>
        <span class="account">
          ${
            profile.isPending
              ? nothing
              : profile.data
                ? html`<devhub-account-menu
                    .profile=${profile.data}
                  ></devhub-account-menu>`
                : this.#loginLink()
          }
        </span>
      </div>
    `;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'devhub-header': DevhubHeader;
  }
}
